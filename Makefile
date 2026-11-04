ROOT := $(CURDIR)
PLIST := $(HOME)/Library/LaunchAgents/com.aryan.booksync.plist

.PHONY: install test status sync agent agent-remove

install:
	uv sync

test:
	.venv/bin/python -m pytest -q

status:
	bin/booksync status

sync:
	bin/booksync sync

agent:
	@mkdir -p $(HOME)/Library/LaunchAgents $(HOME)/Library/Logs
	@sed -e "s|__ROOT__|$(ROOT)|g" -e "s|__HOME__|$(HOME)|g" \
		launchd/com.aryan.booksync.plist > $(PLIST)
	@launchctl unload $(PLIST) 2>/dev/null || true
	@launchctl load $(PLIST)
	@echo "installed: daily sync at 09:15 ($(PLIST))"

agent-remove:
	@launchctl unload $(PLIST) 2>/dev/null || true
	@rm -f $(PLIST)
	@echo "removed"
