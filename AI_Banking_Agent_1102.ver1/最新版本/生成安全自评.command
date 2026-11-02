#!/bin/sh
cd "$(dirname "$0")" || exit 1
python3 -B -m security_integration.self_assess
