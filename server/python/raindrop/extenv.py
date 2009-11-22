# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Raindrop.
#
# The Initial Developer of the Original Code is
# Mozilla Messaging, Inc..
# Portions created by the Initial Developer are Copyright (C) 2009
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#

# The raindrop 'extension environment'.  Responsible for setting up all the
# globals available to extensions.
import uuid
from twisted.internet import defer, threads
from twisted.internet import reactor

import logging

logger = logging.getLogger(__name__)

__my_identities = []

def get_ext_env(doc_model, context, src_doc, ext):
    # Hack together an environment for the extension to run in
    # (specifically, provide the emit_schema etc globals)
    # NOTE: These are all called in the context of a worker thread and
    # are expected by the caller to block.
    new_items = context['new_items']
    def emit_schema(schema_id, items, rd_key=None, attachments=None, deps=None):
        ni = {'rd_schema_id': schema_id,
              'items': items,
              'rd_ext_id' : ext.id,
              }
        if rd_key is None:
            ni['rd_key'] = src_doc['rd_key']
        else:
            ni['rd_key'] = rd_key
        if deps is not None:
            ni['rd_deps'] = deps
        ni['rd_source'] = [src_doc['_id'], src_doc['_rev']]
        if attachments is not None:
            ni['attachments'] = attachments
        if ext.category in [ext.PROVIDER, ext.SMART]:
            ni['rd_schema_provider'] = ext.id
        new_items.append(ni)
        return doc_model.get_doc_id_for_schema_item(ni)

    def emit_related_identities(identity_ids, def_contact_props):
        logger.debug("emit_related_identities for %r", ext.id)
        for item in items_from_related_identities(doc_model,
                                             identity_ids,
                                             def_contact_props,
                                             ext.id):
            item['rd_source'] = [src_doc['_id'], src_doc['_rev']]
            new_items.append(item)
        logger.debug("emit_related_identities for %r - now %d items",
                     ext.id, len(new_items))

    def emit_convo_relations(msg_ids, conv_id):
        logger.debug("emit_convo_relations for %r", ext.id)
        for item in items_from_convo_relations(doc_model,
                                                msg_ids, conv_id, ext.id):
            item['rd_source'] = [src_doc['_id'], src_doc['_rev']]
            new_items.append(item)
        logger.debug("emit_convo_relations for %r - now %d items",
                     ext.id, len(new_items))

    def open_schema_attachment(src, attachment, **kw):
        "A function to abstract document storage requirements away..."
        doc_id = src['_id']
        dm = doc_model
        found, info = dm.get_schema_attachment_info(src, attachment)
        logger.debug("attempting to open attachment %s/%s", doc_id, found)
        return threads.blockingCallFromThread(reactor,
                    dm.db.openDoc, dm.quote_id(doc_id),
                    attachment=found, **kw)

    def open_view(*args, **kw):
        context['did_query'] = True
        return threads.blockingCallFromThread(reactor,
                    doc_model.open_view, *args, **kw)

    def open_schemas(*args, **kw):
        return threads.blockingCallFromThread(reactor,
                    doc_model.open_schemas, *args, **kw)

    def update_documents(docs):
        context['did_query'] = True
        assert docs, "please fix the extension to not bother calling with no docs!"
        return threads.blockingCallFromThread(reactor,
                    doc_model.update_documents, docs)

    def get_my_identities():
        # XXX - can't use globals here - so we cheat!
        from raindrop.extenv import __my_identities
        # Some extensions need to know which identity IDs mean the current
        # user for various purposes - eg, "was it sent to/from me?".
        # We could let such extensions use open_view, but then it would
        # be flagged as a 'dynamic' extension when it isn't really.
        # So - abstract some of that behind this helper.
        # For now, assume identities don't change between runs.  Later we
        # could listen for changes to account schemas in the pipeline and
        # invalidate...
        if not __my_identities:
            result = threads.blockingCallFromThread(reactor,
                        doc_model.open_view,
                        startkey=["rd.account", "identities"],
                        endkey=["rd.account", "identities", {}],
                        reduce=False,
                        )
            for row in result['rows']:
                iid = row['key'][2]
                # can't use a set - identity_ids are lists!
                if iid not in __my_identities:
                    __my_identities.append(iid)
        return __my_identities

    new_globs = {}
    new_globs['emit_schema'] = emit_schema
    new_globs['emit_related_identities'] = emit_related_identities
    new_globs['emit_convo_relations'] = emit_convo_relations
    new_globs['open_schema_attachment'] = open_schema_attachment
    new_globs['open_schemas'] = open_schemas
    new_globs['get_schema_attachment_info'] = doc_model.get_schema_attachment_info
    new_globs['open_view'] = open_view
    new_globs['update_documents'] = update_documents
    new_globs['get_my_identities'] = get_my_identities
    new_globs['logger'] = logging.getLogger('raindrop.ext.'+ext.id)
    return new_globs


# NOTE: called from a background thread by extensions, so we can block :)
def items_from_related_identities(doc_model, idrels, def_contact_props, ext_id):
    idrels = list(idrels) # likely a generator...
    assert idrels, "don't give me an empty list - just don't emit!!"
    if __debug__: # check the extension is sane...
        for iid, rel in idrels:
            assert isinstance(iid, (tuple, list)) and len(iid)==2,\
                   repr(iid)
            assert rel is None or isinstance(rel, basestring), repr(rel)

    # Take a short-cut to ensure all identity records exist and to
    # handle conflicts from the same identity being created at the
    # same time; ask the doc-model to emit a NULL schema for each
    # one if it doesn't already exist.
    for iid, rel in idrels:
        yield {'rd_key' : ['identity', iid],
               'rd_schema_id' : 'rd.identity.exists',
               'items': None,
               'rd_ext_id' : ext_id,
               }

    # Find contacts associated with any and all of the identities;
    # any identities not associated with a contact will be updated
    # to have a contact (either one we find with for different ID)
    # or a new one we create.
    # XXX - can we safely do this in parallel?
    wanted = []
    for iid, rel in idrels:
        # the identity itself.
        rdkey = ['identity', iid]
        wanted.append((rdkey, 'rd.identity.contacts'))

    results = threads.blockingCallFromThread(reactor,
                    doc_model.open_schemas, wanted)

    assert len(results)==len(idrels), (results, idrels)

    # scan the list looking for an existing contact for any of the ids.
    for schema in results:
        if schema is not None:
            contacts = schema.get('contacts', [])
            if contacts:
                contact_id = contacts[0][0]
                logger.debug("Found existing contact %r", contact_id)
                break
    else: # for loop not broken...
        # allocate a new contact-id; we can't use a 'natural key' for a
        # contact....
        contact_id = str(uuid.uuid4())
        # just choose any of the ID's details (although first is likely
        # to be 'best')
        cdoc = {}
        # We expect a 'name' field at least...
        assert 'name' in def_contact_props, def_contact_props
        cdoc.update(def_contact_props)
        logger.debug("Will create new contact %r", contact_id)
        yield {'rd_key' : ['contact', contact_id],
               'rd_schema_id' : 'rd.contact',
               # ext_id might be wrong here - maybe it should be 'us'?
               'rd_ext_id' : ext_id,
               'items' : cdoc,
        }

    # We know the contact to use and the list of identities
    # which we know exist. We've also got the 'contacts' schemas for
    # those identities - which may or may not exist, and even if they do,
    # may not refer to this contact.  So fix all that...
    for schema, (iid, rel) in zip(results, idrels):
        # identity ID is a tuple/list of exactly 2 elts.
        assert isinstance(iid, (tuple, list)) and len(iid)==2, repr(iid)
        new_rel = (contact_id, rel)
        doc_id = doc_rev = None # incase we are updating a doc...
        if schema is None:
            # No 'contacts' schema exists for this identity
            new_rel_fields = {'contacts': [new_rel]}
        else:
            existing = schema.get('contacts', [])
            logger.debug("looking for %r in %s", contact_id, existing)
            for cid, existing_rel in existing:
                if cid == contact_id:
                    new_rel_fields = None
                    break # yay
            else:
                # not found - we need to update this doc
                new_rel_fields = schema.copy()
                sch['contacts'] = existing + [new_rel]
                logger.debug("new relationship (update) from %r -> %r",
                             iid, contact_id)
                # and note the fields which allows us to update...
                doc_id = schema['_id']
                doc_rev = schema['_rev']
        if new_rel_fields is not None:
            yield {'rd_key' : ['identity', iid],
                   'rd_schema_id' : 'rd.identity.contacts',
                   'rd_ext_id' : ext_id,
                   'items' : new_rel_fields,
            }

# XXX - this is very close logically to items_from_related_identities - it
# needs to be refactored!
def items_from_convo_relations(doc_model, msg_keys, conv_id, ext_id):
    # conv_id may be None - in which case we look for an existing convo
    # with any of the messages.  If we don't find one, we create a new one.
    # If conv_id is not None, that conv ID will be used, creating it if
    # necessary.  Consider the 2 use cases:
    # 1) Email does not have the concept of a canonical conversation - a
    # conversation is "derived" from related messages.  None should always
    # be passed in this case.
    # 2) Skype has the concept of a "chat" and messages within that chat.
    # In this case, the skype provided ID for the chat should be used.

    msg_keys = list(msg_keys) # likely a generator...
    assert msg_keys, "don't give me an empty list - just don't emit!!"

    if conv_id is None:
        # Find conversations associated with any and all of the messages;
        # any messages not associated with a contact will be updated
        # to have a contact (either one we find with for different ID)
        # or a new one we create.
        results = []
        keys = [['rd.conv.messages', 'messages', rdkey] for rdkey in msg_keys]
        results = threads.blockingCallFromThread(reactor,
                        doc_model.open_view, keys=keys, reduce=False)
        # run over the results - in the perfect world there would be exactly
        # one (or zero) convo IDs returned.  More than 1 means something is
        # out of synch.
        all_conv_keys = set()
        for row in results['rows']:
            all_conv_keys.add(doc_model.hashable_key(tuple(row['value']['rd_key'])))
        if len(all_conv_keys) == 0:
            # make a new one; the conv_id will include the entire rd_key
            # of one of the messages to avoid conflicts between different
            # 'providers' (eg, while a msg-id should be unique within emails,
            # there is nothing to prevent a 'skype chat ID' conflicting with
            # a message-id.)
            conv_id = ['conv', msg_keys[0]]
        elif len(all_conv_keys) == 1:
            # yay - an existing one.
            conv_id = list(all_conv_keys)[0]
        else:
            # we must *merge* the 2 conversations together.  Pick one
            # to use and arrange to delete the others.
            logger.debug("The set of messages %s appear in multiple conversations %s",
                        msg_keys, all_conv_keys)
            # just pick one of them
            all_keys = list(all_conv_keys)
            conv_id = all_keys[0]
            dids = []
            for todel in all_keys[1:]:
                # XXX - is this enough?  Should we nuke *all* schemas with
                # the rd_key of the convo?
                schids = ['rd.conv.messages', 'rd.conv.summary']
                for schid in schids:
                    tempsi = {'rd_key': todel,
                              'rd_schema_id':schid,
                              }
                    dids.append(doc_model.get_doc_id_for_schema_item(tempsi))
            docs = threads.blockingCallFromThread(reactor,
                                doc_model.open_documents_by_id, dids)
            docs = [doc for doc in docs if doc is not None]
            threads.blockingCallFromThread(reactor,
                                doc_model.delete_documents, docs)

    # attempt to open the specified convo so we can adjust the messages.
    cdoc = threads.blockingCallFromThread(reactor,
                doc_model.open_schemas, [(conv_id, 'rd.conv.messages')])[0]
    if cdoc is None:
        cdoc = {'messages' : []}

    messages = set((doc_model.hashable_key(m) for m in cdoc['messages']))
    for rdkey in msg_keys:
        messages.add(doc_model.hashable_key(rdkey))
    # we keep the message-list sorted so abitrary ordering doesn't cause the
    # document to be considered different when it is semantically identical.
    # We don't care *what* it is sorted by, so long as it is deterministic.
    cdoc['messages'] = sorted(list((list(m) for m in messages)))
    yield {'rd_schema_id': 'rd.conv.messages',
           'rd_key': conv_id,
           'rd_ext_id': ext_id,
           'rd_schema_provider': ext_id,
           'items': cdoc}
