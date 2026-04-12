.PHONY: install build-ui clean clean-start

install: build-ui
	pip install -e .

build-ui:
	cd web && npm install && npm run build
	rm -rf vigil/ui/assets vigil/ui/index.html vigil/ui/favicon.svg vigil/ui/__pycache__
	cp -r web/dist/* vigil/ui/

clean:
	rm -rf vigil/ui/assets vigil/ui/index.html vigil/ui/favicon.svg vigil/ui/__pycache__ web/dist web/node_modules

# Wipe web + bundled UI artifacts, reinstall deps, rebuild UI, editable install, then run Vigil (blocks until Ctrl+C).
clean-start: clean install
	vigil start --config vigil.yaml
