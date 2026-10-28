"""Terminate an entire worker process group if its owning runner disappears."""

import os, signal, subprocess, sys, threading


def watch_parent():
    parent = os.getppid()

    def watch():
        while True:
            threading.Event().wait(0.5)
            if os.getppid() != parent or parent == 1:
                os.killpg(os.getpgrp(), signal.SIGTERM)
                return

    threading.Thread(target=watch, daemon=True).start()


if __name__ == "__main__":
    watch_parent()
    raise SystemExit(subprocess.call(sys.argv[1:]))
