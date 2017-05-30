#!/usr/bin/python

from __future__ import print_function
import os
import sys
import atexit
import signal
import grp
import pwd
import string
import re
import pyinotify
import smtplib

#global>>>>
watch_file='/root/monitorlist.txt'
logfile_name = '/root/logs/sftp-monitor.log'
logfile_save= '/root/logs/sftp-monitor.log.save'
PIDFILE = '/var/run/sftp-monitor.pid'

watch_list = []
watch_dict = {}
#global <<<<

def daemonize(pidfile,stdin='/dev/null',stdout='/dev/null',stderr='/dev/null') :
    #
    if os.path.exists(pidfile):
        raise RuntimeError('Already running')
        # First fork (detaches from parent)
        # Because the parent process has terminated, the child process now runs in the background.
    try:
        if os.fork() > 0:
            raise SystemExit(0) # Parent exit
    except OSError as e :
        raise RuntimeError('fork #1 failed.')
    # first fork has succeded
    os.chdir('/var/tmp')
    os.umask(0)
    os.setsid()
    # setsid New session. The calling process becomes the leader of the new session and the process group leader of the new process group. 
    # The process is now detached from its controlling terminal (CTTY).
    # 
    # Second fork (relinquish session leadership)
    # fork again and let the parent process terminate to ensure that you get rid of the session leading process.  
    try:
        if os.fork() > 0:
            raise SystemExit(0)
    except OSError as e:
        raise RuntimeError('fork #2 failed.')

    # Flush I/O buffers
    sys.stdout.flush()
    sys.stderr.flush()
    # Replace file descriptors for stdin, stdout, and stderr
    with open(stdin, 'rb', 0) as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open(stdout, 'ab', 0) as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
    with open(stderr, 'ab', 0) as f:
        os.dup2(f.fileno(), sys.stderr.fileno())

# Write the PID file
    with open(pidfile,'w') as f:
        f.write(str(os.getpid()))
# Arrange to have the PID file removed on exit/signal
    atexit.register(lambda: os.remove(pidfile))
# Signal handler for termination (required)

def sigterm_handler(signo, frame):
    raise SystemExit(1)

signal.signal(signal.SIGTERM, sigterm_handler)

def sender(owner,filename,event,recipient):
    sender = 'DAEMON@ip-10-0-200-251.eu-west-1.compute.internal'

    short_subject = "File arrived from "+owner
    body_text = "File " + filename + " from " + owner + " " + event
    message = string.join((
            "From: %s" % sender ,
            "To: %s" % recipient ,
            "Subject: %s" % short_subject ,
            "",
            body_text
            ), "\r\n")

    try:
       smtpObj = smtplib.SMTP('localhost')
       smtpObj.sendmail(sender, recipient, message)
       print("Successfully sent email\n", file=sys.stderr)
    except smtplib.SMTPException:
       print("Error: unable to send email\n", file=sys.stderr)

def find_path(path):
    while ( path != '/' ):
        if path in watch_dict.keys():
            if (watch_dict[path]):
                return path
        path = os.path.dirname(path)

def main():
    import time
    import os.path
    import string

    print('starting main ' + str(os.getpid())  + '\n', file=sys.stderr)

    list_file = open(watch_file,'r')    # file: /path/:email@user
    for fline in list_file:
        if ( os.path.exists(fline[:fline.find(':')])):
            wpath,watcher = fline.strip().split(':')
            watch_dict[wpath] = watcher
            watch_list.append(wpath)
            print(wpath + " directory exists - will monitor for "+ watcher, file=sys.stderr)
        else:
            print(fline.strip() +  " does not exist, ignoring\n", file=sys.stderr)
    list_file.close()

    mask = pyinotify.IN_DELETE | pyinotify.IN_CREATE  # watched events outside class because we may have more than one criteria

    # The watch manager stores the watches and provides operations on watches
    wm = pyinotify.WatchManager() # watch manager
    handler = EventHandler()      # instance to act on the event

    notifier = pyinotify.Notifier(wm, handler)
    # Internally, 'handler' is a callable object which on new events will be called like this: handler(new_event)

    #wdd = wm.add_watch(watch_list, mask, rec=True, auto_add=True)
    wm.add_watch(watch_list, mask, rec=True, auto_add=True)

    # this needs to be an array or a hash or /sftp-data/chroot auto_add is to add new directories added during run
    # rec=True is recusrive so just need to handle the file names and to exclude sax-backups and ktech
    # Note: it is not possible to exclude a file if its encapsulating
    #      directory is itself watched. See this issue for more details      https://github.com/seb-m/pyinotify/issues/31
    notifier.loop()
    # will exit on ctrl-c SIGINT

class EventHandler(pyinotify.ProcessEvent):
    def process_IN_CREATE(self, event):
        ckp = find_path(os.path.dirname(event.pathname))
        try:
            stat_info = os.stat(event.pathname)      
        except:
            print ("Error encountered with ",event.pathname, file=sys.stderr)
            pass 
        uid = stat_info.st_uid
        owner = pwd.getpwuid(uid)[0]

        if (watch_dict.has_key(ckp)):
            print ("File",event.pathname,"for ",owner," notify ",watch_dict[ckp], file=sys.stderr)
            if (re.search('\.filepart$',event.pathname)) :
                pass # partial file the event for the complete file will be along shortly
            else:
                searchObj = re.search('(^.*\/)?(.*$)',event.pathname) # extract the file name alone into group 2
                fname = searchObj.group(2) 
                sender(owner,fname,'arrived',watch_dict[ckp])

    def process_IN_DELETE(self, event):
        pass # may want this later though


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: {} [start|stop|status]'.format(sys.argv[0]), file = sys.stderr)
        raise SystemExit(1)

    if sys.argv[1] == 'start':
        try:
            daemonize(PIDFILE,
            stdout=logfile_name,
            stderr=logfile_name)
        except RuntimeError as e:
            print(e, file=sys.stderr)
            raise SystemExit(1)

        main()

    elif sys.argv[1] == 'stop':
        if os.path.isfile(logfile_name) :
            os.rename(logfile_name,logfile_save)
        if os.path.exists(PIDFILE):
            with open(PIDFILE) as f:
                    os.kill(int(f.read()), signal.SIGTERM)
                    print ("Killed",file=sys.stderr)
        else:
            print('Not running', file=sys.stderr)
            raise SystemExit(1)

    elif sys.argv[1] == 'status':
        if os.path.exists(PIDFILE):
             with open(PIDFILE) as f:
                    try: 
                        os.kill(int(f.read()), 0)
                        print('running',file=sys.stderr)
                    except: 
                        print('Not running', file=sys.stderr)
        else:
            print('No PID file', file=sys.stderr)
    else:
        print('Unknown command {!r}'.format(sys.argv[1]), file=sys.stderr)
        raise SystemExit(1)

