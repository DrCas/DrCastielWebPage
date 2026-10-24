#!/bin/sh
set -eu
/usr/sbin/nginx -t -c /etc/drcastiel/casa-nginx.conf
/bin/systemctl reload drcastiel-casa.service
