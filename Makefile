# Used by `sam build` (BuildMethod: makefile in deploy/lambda/template.yaml).
# Copies only the files the app needs, so .env, .venv, data/ and samples/ never reach Lambda.
# Dependencies are Linux wheels downloaded by uv, so no Docker is needed on macOS.
UV ?= uv

build-WebFunction:
	cp app.py store.py "$(ARTIFACTS_DIR)/"
	cp -R templates static "$(ARTIFACTS_DIR)/"
	cp deploy/lambda/run.sh "$(ARTIFACTS_DIR)/run.sh"
	chmod +x "$(ARTIFACTS_DIR)/run.sh"
	$(UV) pip install --quiet -r requirements.txt --target "$(ARTIFACTS_DIR)" \
		--python-platform x86_64-manylinux2014 --python-version 3.13 --only-binary :all:
