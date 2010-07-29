
VERSION=$(shell python setup.py --version)
VERSION_TAG=v$(subst .,_,$(VERSION))
TARFILE=archivemail-$(VERSION).tar.gz
HTDOCS=htdocs-$(VERSION)

default:
	@echo "no default target"

clean:
	rm -f *.pyc manpage.links manpage.refs manpage.log
	rm -rf $(HTDOCS)

test:
	python test_archivemail

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
	git tag -a $(VERSION_TAG)

upload:
	(cd dist && lftp -c 'open upload.sf.net && cd incoming && put $(TARFILE)')

doc: archivemail.1 archivemail.html

htdocs: $(HTDOCS).tgz
$(HTDOCS).tgz: index.html archivemail.html RELNOTES style.css manpage.css
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
