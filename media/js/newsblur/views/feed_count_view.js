NEWSBLUR.Views.FeedCount = Backbone.View.extend({
    
    className: 'feed_counts_floater',
    
    initialize: function() {
        _.bindAll(this, 'render');
        if (!this.options.stale) {
            this.model.bind('change:ps', this.render);
            this.model.bind('change:nt', this.render);
            this.model.bind('change:ng', this.render);
        }
    },
    
    // ==========
    // = Render =
    // ==========
    
    render: function() {
        var unread_class = "";
        var counts = this.model.unread_counts();

        if (counts['ps']) {
            unread_class += ' unread_positive';
        }
        if (counts['nt']) {
            unread_class += ' unread_neutral';
        }
        if (counts['ng']) {
            unread_class += ' unread_negative';
        }
        
        this.$el.html(this.template({
          ps           : counts['ps'],
          nt           : counts['nt'],
          ng           : counts['ng'],
          unread_class : unread_class
        }));
        
        return this;
    },
    
    template: _.template('\
        <div class="<%= unread_class %>">\
          <span class="unread_count unread_count_positive <% if (ps) { %>unread_count_full<% } else { %>unread_count_empty<% } %>">\
            <%= ps %>\
          </span>\
          <span class="unread_count unread_count_neutral <% if (nt) { %>unread_count_full<% } else { %>unread_count_empty<% } %>">\
            <%= nt %>\
          </span>\
          <span class="unread_count unread_count_negative <% if (ng) { %>unread_count_full<% } else { %>unread_count_empty<% } %>">\
            <%= ng %>\
          </span>\
        </div>\
    '),
    
    // ===========
    // = Actions =
    // ===========
    
    center: function() {
        var i_width = this.$el.width();
        var o_width = NEWSBLUR.reader.$s.$story_taskbar.width();
        var left = (o_width / 2.0) - (i_width / 2.0);
        var view_taskbar_width = $('.NB-taskbar-view').outerWidth(true);
        var story_buttons_offset = $(".NB-taskbar-nav").position().left;

        if (i_width + 12 > (story_buttons_offset - view_taskbar_width)) {
            this.$el.hide();
        }
        
        if (left < view_taskbar_width + 12) {
            left += view_taskbar_width - left + 12;
        }
        this.$el.css({'left': left});
    },
    
    flash: function() {
        var $floater = this.$el;
        
        if (!NEWSBLUR.assets.preference('animations')) return;
        
        _.defer(function() {
            $floater.animate({'opacity': 1}, {'duration': 250, 'queue': false});
            _.delay(function() {
                $floater.animate({'opacity': .2}, {'duration': 250, 'queue': false});
            }, 400);
        });        
    },
    
    fall: function() {
        var $floater = this.$el;
        
        _.delay(function() {
            $floater.animate({
                'top': $('#story_taskbar').height()
            }, {
                'duration': 500, 
                'queue': false,
                'easing': 'easeOutQuint'
            });
        }, 500);
    }
    
});