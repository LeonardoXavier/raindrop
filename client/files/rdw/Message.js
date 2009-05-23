dojo.provide("rdw.Message");

dojo.require("rdw._Base");
dojo.require("rd.identity");
dojo.require("rdw.gravatar");
dojo.require("rd.friendly");
dojo.require("rd.hyperlink");

dojo.declare("rdw.Message", [rdw._Base], {
  //Suggested values for type are "topic" and "reply"
  type: "topic",

  //Holds the aggregated message object.
  //Warning: this is a prototype property: be sure to
  //set it per instance.
  messageBag: {},

  templatePath: dojo.moduleUrl("rdw.templates", "Message.html"),

  blankImgUrl: dojo.moduleUrl("rdw.resources", "blank.png"),

  postMixInProperties: function() {
    //summary: dijit lifecycle method
    this.inherited("postMixInProperties", arguments);
    
    //Set the properties for this widget based on messageBag
    //properties.
    //TODO: some of these need more info from backend.    
    // XXX: these are a couple hacks to get the UI looking more like we want
    var msgBag = this.messageBag;
    var msgDoc = msgBag['rd/msg/body'];

    this.fromName = msgDoc.from[1];
    try {
      var pieces = msgDoc.from[1].split("<");
      if(pieces && pieces[0]) {
        this.fromName = pieces[0];
      }
    } catch(ignore) { }
    
    this.fromId = msgDoc.from[1];
    try {
      var matches = msgDoc.from[1].match(/<(.+)>/);
      if(matches && matches[1]) {
        this.fromId = matches[1].toLowerCase();
      }
    } catch(ignore) { }

    this.subject = null;
    this.subject = rd.escapeHtml(msgDoc.subject ?
                                msgDoc.subject.replace(/^Re:/,'') : "");

    //TODO: make message transforms extensionized.
    this.message = rd.hyperlink.add(rd.escapeHtml(msgDoc.body_preview));
    if(msgDoc.from[0] == "twitter") {
      this.message = rd.hyperlink.addTwitterUsers(this.message);
      this.message = rd.hyperlink.addTwitterTags(this.message);
    }

    this.time = msgDoc.timestamp;

    /* XXX this timestamp needs a lot more thought to show the right kind of 
       time info and we probably also want to some standard the hCard formatting */
    var fTime = rd.friendly.timestamp(msgDoc.timestamp);
    this.utcTime = fTime["utc"];
    this.friendlyTime = fTime["friendly"];
    this.additionalTime = fTime["additional"];
    
    this.userPicUrl = this.blankImgUrl;
    //If the fromId has an @ in it, try to use a gravatar for it.
    if (this.fromId && this.fromId.indexOf("@") != -1) {
      this.userPicUrl = rdw.gravatar.get(this.fromId);
    }
  },

  postCreate: function() {
    //summary: dijit lifecycle method
    this.inherited("postCreate", arguments);

    //If twitter user, get their profile pic.
    var msgBag = this.messageBag;
    var msgDoc = msgBag['rd/msg/body'];
    var from = msgDoc.from;
    rd.identity.get(from, dojo.hitch(this, function(user) {
      if (user.image) {
        if (user.image[0]=="/")
          // It is a URL into our couch.
          this.userPicNode.src = "/raindrop" + user.image;
        else
          // it is an absolute URL...
          this.userPicNode.src = user.image;
      }
      if (user.name) {
        this.fromNameNode.innerHTML = rd.escapeHtml(user.name);
      }
      //Don't worry about errors, just will not show pic.
    }), function(err){console.error(err)});
  },

  onToolClick: function(evt) {
    //summary: handles clicks for tool actions. Uses event
    //delegation to publish the right action.
    var href = evt.target.href;
    if (href && (href = href.split("#")[1])) {
      rd.pub("rdw.Message-" + href, {
        widget: this,
        messageBag: this.messageBag
      });
      evt.preventDefault();
    }
  },

  addByTopic: function(/*Object*/widget, /*String*/topic, /*Object*/topicData) {
    //summary: rdw._Base method override for reply/forward widget extensions.
    this.inherited("addByTopic", arguments);

    //If we have an existing response widget, despose of it
    //properly, then use the new widget as the response widget.
    if (this.responseWidget) {
      this.removeByTopic(widget, topic, topicData);
      this.responseWidget.destroy();
    }
    this.responseWidget = widget;

    //Put the response widget in the toolDisplay
    widget.placeAt(this.toolDisplay);

    //Hide the reply/forward controls.
    this.tools.style.display = "none";
  },

  removeByTopic: function(/*Object*/widget, /*String*/topic, /*Object*/topicData) {
    //summary: rdw._Base method override for reply/forward widget extensions.
    this.inherited("removeByTopic", arguments);

    //Show the reply/forward controls.
    this.tools.style.display = "";
  }
});
