#!/usr/bin/env python

'''
Setup the CouchDB server so that it is fully usable and what not.
'''
import model

import os, os.path, mimetypes, base64, pprint

import junius.model as model

def setup_account(dbs):
    if len(model.Account.all(dbs.accounts)):
        print 'Account presumably already exists, not adding it!'
        return
    
    # we want a file of the form:
    #  hostname,port,username,password,ssl?
    # example:
    #  mail.example.com,993,bob@example.com,sekret,True
    import os, os.path
    configPath = os.path.join(os.environ['HOME'], ".junius")
    f = open(configPath, 'r')
    data = f.read()
    f.close()
    host, portstr, username, password, sslstr = data.split(',')
    ssl = not (sslstr.lower() in ['false', 'f', 'no', '0'])
    
    account = model.Account(
        kind='imap', host=host, port=int(portstr), ssl=ssl,
        username=username, password=password,
    )
    account.store(dbs.accounts)

def path_part_nuke(path, count):
    for i in range(count):
        path = os.path.dirname(path)
    return path
    

FILES_DOC = 'files' #'_design/files'

def install_client_files(dbs):
    '''
    cram everyone in 'client' into the 'junius' app database
    '''
    if FILES_DOC in dbs.junius:
        print 'Design doc already exists, will be updating/overwriting files'
        design_doc = dbs.junius[FILES_DOC]
        attachments = design_doc['_attachments'] = {}
    else:
        design_doc = {}
        attachments = design_doc['_attachments'] = {}
    
    # we cannot go in a zipped egg...
    junius_root_dir = path_part_nuke(model.__file__, 4)
    client_dir = os.path.join(junius_root_dir, 'client')
    print 'listing contents of', client_dir
    
    for filename in os.listdir(client_dir):
        print 'filename', filename
        path = os.path.join(client_dir, filename)
        if os.path.isfile(path):
            f = open(path, 'rb')
            attachments[filename] = {
                'content_type': mimetypes.guess_type(filename)[0],
                'data': base64.b64encode(f.read())
            }
            f.close()
    
    dbs.junius[FILES_DOC] = design_doc


def main():
    import sys
    if 'nuke' in sys.argv:
      print 'NUKING DATABASE!!!'
      model.nuke_db()

    dbs = model.fab_db(update_views='updateviews' in sys.argv)

    setup_account(dbs)
    install_client_files(dbs)
    

if __name__ == '__main__':
    main()
