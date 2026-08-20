.PHONY: check test build test-pathfinder run-pathfinder
PYTHON ?= python3
test:
	npm test
build:
	npm run build
test-pathfinder:
	cd tools/pathfinder && $(PYTHON) -m unittest discover -s tests -v
run-pathfinder:
	cd tools/pathfinder && $(PYTHON) web_app.py
check: test build test-pathfinder
