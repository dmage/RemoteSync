import sublime
import sublime_plugin
import os
import subprocess
from threading import Thread


def run_script(path, filename, code, script, success_message):
    proc = subprocess.Popen(["/bin/sh", "-s", path, filename],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)
    (out, err) = proc.communicate("""
        DISABLE=
        WORKDIR=$1
        FILENAME=$2
        . "$WORKDIR/.remotesync"

        if [ -n "$DISABLE" ]; then
            exit
        fi

        : ${REMOTE_USER:=$(whoami)}
        : ${REMOTE_PORT:=22}
        : ${RSYNC_OPTIONS:=}
    """ + script)

    retcode = proc.returncode
    if retcode is None:
        sublime.error_message("RemoteSync: unexpected error, " + code +
                              " still running.\n" + out + "\n" + err)
        return False
    elif retcode != 0:
        sublime.error_message("RemoteSync: " + code + " failed [err=" +
                              str(retcode) + "].\n" + out + "\n" + err)
        return False

    def done():
        sublime.status_message(success_message)
    sublime.set_timeout(done, 0)
    return True


class RemoteSyncThread(Thread):
    def __init__(self, path, filename):
        Thread.__init__(self)
        self.path = path
        self.filename = filename

    def run(self):
        done = run_script(self.path, self.filename, "rsync", r"""
            REMOTE_USERHOST="$REMOTE_USER@$REMOTE_HOST"
            FILE=${FILENAME/$WORKDIR\//}
            DIR=`dirname "$REMOTE_PATH/$FILE"`

            RSYNC_CMD="rsync -av $RSYNC_OPTIONS"
            ssh -n -p "$REMOTE_PORT" "$REMOTE_USERHOST" mkdir -p "$DIR"
            $RSYNC_CMD -e "ssh -p $REMOTE_PORT" \
                "$WORKDIR/$FILE" "$REMOTE_USERHOST:$REMOTE_PATH/$FILE"
            RSYNC_RETCODE=$?

            exit $RSYNC_RETCODE
        """, "File " + self.filename + " synced")
        if not done:
            return

        done = run_script(self.path, self.filename, "local command", """
            if [ -n "$LOCAL_POST_COMMAND" ]; then
                cd "$WORKDIR"
                eval "$LOCAL_POST_COMMAND"
            fi
        """, "Local command completed successfully")
        if not done:
            return

        done = run_script(self.path, self.filename, "remote command", """
            if [ -n "$REMOTE_POST_COMMAND" ]; then
                ssh -n -p "$REMOTE_PORT" "$REMOTE_USER@$REMOTE_HOST" -- \
                    "cd \"$REMOTE_PATH\" && $REMOTE_POST_COMMAND"
            fi
        """, "Remote command completed successfully")
        if not done:
            return


class RsyncOnSave(sublime_plugin.EventListener):
    def run_remotesync_thread(self, view, path):
        thread = RemoteSyncThread(path, view.file_name())
        thread.start()

    def on_post_save(self, view):
        filename = view.file_name()
        if filename is None:
            return

        dirname = os.path.dirname(filename)
        while True:
            if os.path.exists(os.path.join(dirname, '.remotesync')):
                self.run_remotesync_thread(view, dirname)
                return

            next_dirname = os.path.dirname(dirname)
            if next_dirname == dirname:
                break
            dirname = next_dirname
