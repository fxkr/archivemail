
VERSION=$(shell python setup.py --version)
VERSION_TAG=v$(subst .,_,$(VERSION))
TARFILE=archivemail-$(VERSION).tar.gz
SVNROOT=https://archivemail.svn.sourceforge.net/svnroot/archivemail
HTDOCS=htdocs-$(VERSION)

default:
	@echo "no default target"

clean:
	rm -f *.pyc manpage.links manpage.refs manpage.log
	rm -rf $(HTDOCS)

test:
	python test_archivemail.py

clobber: clean
	rm -rf build dist
	rm -f $(HTDOCS).tgz


sdist: clobber doc
	cp archivemail.py archivemail
	python setup.py sdist
	rm archivemail

# FIXME: bdist_rpm chokes on the manpage. 
#        This is python/distutils bug #644744
#bdist_rpm: clobber doc
#	cp archivemail.py archivemail
#	python setup.py bdist_rpm
#	rm archivemail

tag:
	# Overwriting tags at least doesn't work with svn << 1.4, 
	# it silently creates a new subidr.  It *may* work with 
	# svn 1.4, I haven't tested it. See svn bug #2188.
	#cvs tag -F current
	@if svn list "$(SVNROOT)/tags" | grep -qx "$(VERSION_TAG)/\?"; then \
	    echo "Tag '$(VERSION_TAG)' already exists, aborting"; \
	else \
	    svn copy . "$(SVNROOT)/tags/$(VERSION_TAG)"; \
	fi

upload:
	(cd dist && lftp -c 'open upload.sf.net && cd incoming && put $(TARFILE)')

doc: archivemail.1 archivemail.html

htdocs: index.html archivemail.html RELNOTES style.css manpage.css
	install -d -m 775 $(HTDOCS)
	install -m 664 $^ $(HTDOCS)
	cd $(HTDOCS) && mv archivemail.html manpage.html
	tar czf $(HTDOCS).tgz $(HTDOCS)

archivemail.1: archivemail.sgml
	docbook2man archivemail.sgml
	chmod 644 archivemail.1

archivemail.html: archivemail.sgml db2html.dsl
	docbook2html --dsl db2html.dsl -u archivemail.sgml
	chmod 644 archivemail.html
	tidy -modify -indent -f /dev/null archivemail.html || true

.PHONY: clean test clobber sdist tag upload doc htdocs 
