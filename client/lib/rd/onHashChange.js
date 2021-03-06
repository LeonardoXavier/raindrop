/* ***** BEGIN LICENSE BLOCK *****
 * Version: MPL 1.1
 *
 * The contents of this file are subject to the Mozilla Public License Version
 * 1.1 (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 * http://www.mozilla.org/MPL/
 *
 * Software distributed under the License is distributed on an "AS IS" basis,
 * WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
 * for the specific language governing rights and limitations under the
 * License.
 *
 * The Original Code is Raindrop.
 *
 * The Initial Developer of the Original Code is
 * Mozilla Messaging, Inc..
 * Portions created by the Initial Developer are Copyright (C) 2009
 * the Initial Developer. All Rights Reserved.
 *
 * Contributor(s):
 * */

/*jslint plusplus: false */
/*global require: false, location: false, setInterval: false, setTimeout: false */
"use strict";

//Simple utility that watches for hash changes and then publishes changes.
require.def("rd/onHashChange", ["rd", "dojo"], function (rd, dojo) {
    var value = location.href.split("#")[1] || "", interval,
        onHashChange = { value: value };
    interval = setInterval(function () {
        var newValue = location.href.split("#")[1] || "";
        if (newValue !== value) {
            onHashChange.value = value = newValue;
            //Use a set timeout so an error on a subscriber does
            //not stop the polling.
            setTimeout(function () {
                dojo.publish("rd/onHashChange", [value]);
            }, 10);
        }
    }, 300);

    return onHashChange;
});
