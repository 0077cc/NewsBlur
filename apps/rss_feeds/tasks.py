import datetime
import os
import shutil
import time
import redis
from celery.task import Task
from utils import log as logging
from utils import s3_utils as s3
from django.conf import settings

class TaskFeeds(Task):
    name = 'task-feeds'

    def run(self, **kwargs):
        from apps.rss_feeds.models import Feed        
        settings.LOG_TO_STREAM = True
        now = datetime.datetime.utcnow()
        start = time.time()
        r = redis.Redis(connection_pool=settings.REDIS_FEED_POOL)
        task_feeds_size = r.llen('update_feeds') * 12
        
        hour_ago = now - datetime.timedelta(hours=1)
        r.zremrangebyscore('fetched_feeds_last_hour', 0, int(hour_ago.strftime('%s')))
        
        now_timestamp = int(now.strftime("%s"))
        queued_feeds = r.zrangebyscore('scheduled_updates', 0, now_timestamp)
        r.zremrangebyscore('scheduled_updates', 0, now_timestamp)
        r.sadd('queued_feeds', *queued_feeds)
        logging.debug(" ---> ~SN~FBQueuing ~SB%s~SN stale feeds (~SB%s~SN/%s queued/scheduled)" % (
                        len(queued_feeds),
                        r.scard('queued_feeds'),
                        r.zcard('scheduled_updates')))
        
        # Regular feeds
        if task_feeds_size < 1000:
            feeds = r.srandmember('queued_feeds', 1000)
            Feed.task_feeds(feeds, verbose=True)
            active_count = len(feeds)
        else:
            active_count = 0
        cp1 = time.time()
        
        # Force refresh feeds
        refresh_feeds = Feed.objects.filter(
            active=True,
            fetched_once=False,
            active_subscribers__gte=1
        ).order_by('?')[:100]
        refresh_count = refresh_feeds.count()
        cp2 = time.time()
        
        # Mistakenly inactive feeds
        hours_ago = (now - datetime.timedelta(hours=6)).strftime('%s')
        old_tasked_feeds = r.zrangebyscore('tasked_feeds', 0, hours_ago)
        inactive_count = len(old_tasked_feeds)
        if inactive_count:
            r.zremrangebyscore('tasked_feeds', 0, hours_ago)
            r.sadd('queued_feeds', *old_tasked_feeds)
            logging.debug(" ---> ~SN~FBRe-queuing ~SB%s~SN dropped feeds (~SB%s~SN queued)" % (
                            inactive_count,
                            r.scard('queued_feeds')))
        cp3 = time.time()
        
        old = now - datetime.timedelta(days=3)
        old_feeds = Feed.objects.filter(
            next_scheduled_update__lte=old, 
            active_subscribers__gte=1
        ).order_by('?')[:500]
        old_count = old_feeds.count()
        cp4 = time.time()
        
        logging.debug(" ---> ~FBTasking ~SB~FC%s~SN~FB/~FC%s~FB (~FC%s~FB/~FC%s~SN~FB) feeds... (%.4s/%.4s/%.4s/%.4s)" % (
            active_count,
            refresh_count,
            inactive_count,
            old_count,
            cp1 - start,
            cp2 - cp1,
            cp3 - cp2,
            cp4 - cp3
        ))
        
        # Feed.task_feeds(feeds, verbose=False)
        Feed.task_feeds(refresh_feeds, verbose=False)
        Feed.task_feeds(old_feeds, verbose=False)

        logging.debug(" ---> ~SN~FBTasking took ~SB%s~SN seconds (~SB%s~SN/~SB%s~SN/%s tasked/queued/scheduled)" % (
                        int((time.time() - start)),
                        r.llen('update_feeds'),
                        r.scard('queued_feeds'),
                        r.zcard('scheduled_updates')))

        
class UpdateFeeds(Task):
    name = 'update-feeds'
    max_retries = 0
    ignore_result = True

    def run(self, feed_pks, **kwargs):
        from apps.rss_feeds.models import Feed
        from apps.statistics.models import MStatistics
        
        mongodb_replication_lag = int(MStatistics.get('mongodb_replication_lag', 0))
        compute_scores = bool(mongodb_replication_lag < 10)
        
        options = {
            'fake': bool(MStatistics.get('fake_fetch')),
            'quick': float(MStatistics.get('quick_fetch', 0)),
            'compute_scores': compute_scores,
            'mongodb_replication_lag': mongodb_replication_lag,
        }
        
        if not isinstance(feed_pks, list):
            feed_pks = [feed_pks]
            
        for feed_pk in feed_pks:
            try:
                feed = Feed.get_by_id(feed_pk)
                if not feed:
                    raise Feed.DoesNotExist
                feed.update(**options)
            except Feed.DoesNotExist:
                logging.info(" ---> Feed doesn't exist: [%s]" % feed_pk)
            # logging.debug(' Updating: [%s] %s' % (feed_pks, feed))

class NewFeeds(Task):
    name = 'new-feeds'
    max_retries = 0
    ignore_result = True

    def run(self, feed_pks, **kwargs):
        from apps.rss_feeds.models import Feed
        if not isinstance(feed_pks, list):
            feed_pks = [feed_pks]
        
        options = {
            'force': True,
        }
        for feed_pk in feed_pks:
            feed = Feed.get_by_id(feed_pk)
            feed.update(options=options)

class PushFeeds(Task):
    name = 'push-feeds'
    max_retries = 0
    ignore_result = True

    def run(self, feed_id, xml, **kwargs):
        from apps.rss_feeds.models import Feed
        from apps.statistics.models import MStatistics
        
        mongodb_replication_lag = int(MStatistics.get('mongodb_replication_lag', 0))
        compute_scores = bool(mongodb_replication_lag < 60)
        
        options = {
            'feed_xml': xml,
            'compute_scores': compute_scores,
            'mongodb_replication_lag': mongodb_replication_lag,
        }
        feed = Feed.get_by_id(feed_id)
        feed.update(options=options)

class BackupMongo(Task):
    name = 'backup-mongo'
    max_retries = 0
    ignore_result = True
    
    def run(self, **kwargs):
        COLLECTIONS = "classifier_tag classifier_author classifier_feed classifier_title userstories starred_stories shared_stories category category_site sent_emails social_profile social_subscription social_services statistics feedback"

        date = time.strftime('%Y-%m-%d-%H-%M')
        collections = COLLECTIONS.split(' ')
        db_name = 'newsblur'
        dir_name = 'backup_mongo_%s' % date
        filename = '%s.tgz' % dir_name

        os.mkdir(dir_name)

        for collection in collections:
            cmd = 'mongodump  --db %s --collection %s -o %s' % (db_name, collection, dir_name)
            logging.debug(' ---> ~FMDumping ~SB%s~SN: %s' % (collection, cmd))
            os.system(cmd)

        cmd = 'tar -jcf %s %s' % (filename, dir_name)
        os.system(cmd)

        logging.debug(' ---> ~FRUploading ~SB~FM%s~SN~FR to S3...' % filename)
        s3.save_file_in_s3(filename)
        shutil.rmtree(dir_name)
        os.remove(filename)
        logging.debug(' ---> ~FRFinished uploading ~SB~FM%s~SN~FR to S3.' % filename)


class ScheduleImmediateFetches(Task):
    
    def run(self, feed_ids, **kwargs):
        from apps.rss_feeds.models import Feed
        
        if not isinstance(feed_ids, list):
            feed_ids = [feed_ids]
        
        Feed.schedule_feed_fetches_immediately(feed_ids)


class SchedulePremiumSetup(Task):
    
    def run(self, feed_ids, **kwargs):
        from apps.rss_feeds.models import Feed
        
        if not isinstance(feed_ids, list):
            feed_ids = [feed_ids]
        
        Feed.setup_feeds_for_premium_subscribers(feed_ids)
        
