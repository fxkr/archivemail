VERSION=$(shell python setup.py --version)
VERSION_TAG=v$(subst .,_,$(VERSION))
TARFILE=archivemail-$(VERSION).tar.gz
HTDOCS=htdocs-$(VERSION)

default:
	@echo "no default target"

clean:
	rm -rf $(HTDOCS)

test:
	python test_archivemail

clobber: clean
	rm -rf build dist
	rm -f $(HTDOCS).tgz


sdist: clobber doc
	python setup.py sdist

tag:
	git tag -a $(VERSION_TAG)

doc: archivemail.1 archivemail.html

htdocs: $(HTDOCS).tgz
$(HTDOCS).tgz: index.html archivemail.html RELNOTES style.css manpage.css
	install -d -m 775 $(HTDOCS)
	install -m 664 $^ $(HTDOCS)
	cd $(HTDOCS) && mv archivemail.html manpage.html
	tar czf $(HTDOCS).tgz $(HTDOCS)

archivemail.1: archivemail.xml db2man.xsl
	xsltproc db2man.xsl archivemail.xml

archivemail.html: archivemail.xml db2html.xsl
	xsltproc --output archivemail.html \
	    db2html.xsl archivemail.xml
	tidy -modify -indent -f /dev/null archivemail.html || true

.PHONY: default clean test clobber sdist tag doc htdocs
