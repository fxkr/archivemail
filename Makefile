
VERSION=0.4.9
VERSION_TAG=v$(subst .,_,$(VERSION))
TARFILE=archivemail-$(VERSION).tar.gz


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
	fakeroot python setup.py sdist
	rm archivemail

bdist_rpm: clobber doc
	cp archivemail.py archivemail
	fakeroot python setup.py bdist_rpm
	rm archivemail

tag:
	cvs tag -F current
	cvs tag -F $(VERSION_TAG)

upload:
	(cd dist && lftp -c 'open upload.sf.net && cd incoming && put $(TARFILE)')

doc: archivemail.1 archivemail.html

archivemail.1: archivemail.sgml
	nsgmls archivemail.sgml | sgmlspl docbook2man-spec.pl 
	chmod 644 archivemail.1

archivemail.html: archivemail.sgml
	jade -t sgml \
	  -d /usr/lib/sgml/stylesheet/dsssl/docbook/nwalsh/html/docbook.dsl \
	  -o archivemail.html \
	  archivemail.sgml
	mv r1.html archivemail.html
	chmod 644 archivemail.html
