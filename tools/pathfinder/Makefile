.PHONY: run test check
PYTHON ?= python3
run:
	$(PYTHON) web_app.py
test:
	$(PYTHON) -m unittest discover -s tests -v
check:
	$(PYTHON) -m compileall -q pathfinder web_app.py tests
	$(PYTHON) -m unittest discover -s tests -v
