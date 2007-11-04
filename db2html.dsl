<!DOCTYPE style-sheet PUBLIC "-//James Clark//DTD DSSSL Style Sheet//EN" [

<!ENTITY dbstyle SYSTEM "/usr/share/sgml/docbook/stylesheet/dsssl/modular/html/docbook.dsl" CDATA DSSSL>
]>
 
<style-sheet>
<style-specification use="docbook">
<style-specification-body>
 
(define %css-decoration% 
    ; Enable html element decoration with 'style=...' css?
#t)

(define %stylesheet% 
    ; Needed if we want to use a css file
"manpage.css")

(define %shade-verbatim%
  ;; Should verbatim environments be shaded?
  #t)
 
</style-specification-body>
</style-specification>
<external-specification id="docbook" document="dbstyle">
</style-sheet>
