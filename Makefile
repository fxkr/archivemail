
VERSION=0.6.2
VERSION_TAG=v$(subst .,_,$(VERSION))
TARFILE=archivemail-$(VERSION).tar.gz
SVNROOT=https://svn.sourceforge.net/svnroot/archivemail


default:
	@echo "no default target"

clean:
	rm -f *.pyc manpage.links manpage.refs manpage.log

test:
	python test_archivemail.py

clobber: clean
	rm -rf build dist


sdist: clobber doc
	cp archivemail.py archivemail
	python setup.py sdist
	rm archivemail

# FIXME: bdist_rpm chokes on the manpage. 
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

archivemail.1: archivemail.sgml
	docbook2man archivemail.sgml
	chmod 644 archivemail.1

archivemail.html: archivemail.sgml
	docbook2html -u archivemail.sgml
	chmod 644 archivemail.html
