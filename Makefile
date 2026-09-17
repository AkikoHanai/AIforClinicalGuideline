.PHONY: setup doctor doctor-online test migration-bundle

setup:
	./scripts/setup_mac.sh

doctor:
	./scripts/doctor_mac.sh

doctor-online:
	./scripts/doctor_mac.sh --online

test:
	.venv/bin/python -m pytest -q

migration-bundle:
	./scripts/package_local_workspace.sh --help
