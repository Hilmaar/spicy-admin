bind = "0.0.0.0:8000"
workers = 2
timeout = 60
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
# U is the path WITHOUT the query string. OAuth codes/state must not enter access logs.
access_log_format = "%(m)s %(U)s %(s)s %(L)s"
capture_output = False
