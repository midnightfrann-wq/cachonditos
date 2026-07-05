#!/bin/bash
git remote remove origin 2>/dev/null
git remote add origin "https://$GITHUB_PERSONAL_ACCESS_TOKEN@github.com/midnightfrann-wq/cachonditos.git"
git push -u origin main
