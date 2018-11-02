"""Utility for ensuring graceful program termination.
"""
CLEANUP_HANDLERS_INSTALLED = False


def install(cleanup):
    import atexit, signal
    global CLEANUP_HANDLERS_INSTALLED

    if CLEANUP_HANDLERS_INSTALLED:
        return

    atexit.register(cleanup)

    def catch_signal(sig, frame):
        cleanup()
        handler = handlers[sig]

        if callable(handler):
            handler(sig, frame)

    signals = [signal.SIGABRT, signal.SIGFPE, signal.SIGILL,
               signal.SIGINT, signal.SIGSEGV, signal.SIGTERM,
               signal.SIGKILL, signal.SIGSTOP, signal.SIGTSTP]

    handlers = {sig: signal.getsignal(sig) for sig in signals}

    for sig in signals:
        try:
            signal.signal(sig, catch_signal)
        except Exception, e:
            pass

    CLEANUP_HANDLERS_INSTALLED = True
