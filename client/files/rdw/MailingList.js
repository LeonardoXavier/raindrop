dojo.provide("rdw.MailingList");

dojo.require("rd.conversation");

dojo.require("rdw._Base");

dojo.declare("rdw.MailingList", [rdw._Base], {
  id: "",
  name: "",

  templatePath: dojo.moduleUrl("rdw.templates", "MailingList.html"),

  postMixInProperties: function() {
    //summary: dijit lifecycle method
    this.inherited("postMixInProperties", arguments);

    // FIXME: this is now only passed with the list ID...
    this.title = this.id = this.doc;
    this.name = this.id.split(".")[0];
//    this.title = this.doc.key[1]; /* this is always either the name or id */
  },

  onClick: function(evt) {
    //summary: handles click delegation when clicking on list of links.
    var target = evt.target;
    if (target.href) {
      target = target.href.split("#")[1];
      if (target) {
        dojo.publish("rd-protocol-" + target);
        dojo.stopEvent(evt);
        this.show(target);
      }
    }
  },

  show: function(id) {
    // Get the rd_key for all items in the mailing-list.
    couch.db("raindrop").view("raindrop!megaview!all/_view/all", {
      key: ["rd/msg/email/mailing-list", "id", id],
      reduce: false,
      success: function(json) {
        //Get message keys
        var rdkeys = [];
        for (var i = 0, row; row = json.rows[i]; i++) {
          rdkeys.push(["rd/msg/conversation", row.value.rd_key]);
        }
        // and yet another view to fetch the convo IDs for these messages.
        couch.db("raindrop").view("raindrop!docs!all/_view/by_raindrop_schema", {
          keys: rdkeys,
          reduce: false,
          include_docs: true,
          success: function(json) {
            //Get conversation IDs.
            // XXX - this isn't working yet :(
            var convIds = [];
            for (var i = 0, row; row = json.rows[i]; i++) {
              convIds.push(row.doc.conversation_id);
            }
            //Load up conversations and ask for them to be displayed.
            rd.conversation(convIds, function(conversations) {
              rd.pub("rd-display-conversations", conversations);
            });
          }
        });
      }
    });
  }
});
