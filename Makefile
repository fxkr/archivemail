
VERSION=0.3.1

default:
	@echo "no default target"

clean:
	rm -f *.pyc 

clobber: clean
	rm -rf build dist

sdist: clobber
	cp archivemail.py archivemail
	fakeroot python setup.py sdist
	rm archivemail
tag:
	cvs tag -F current
	cvs tag v$(VERSION)

archivemail.1: archivemail.sgml
	nsgmls archivemail.sgml | sgmlspl docbook2man-spec.pl 
