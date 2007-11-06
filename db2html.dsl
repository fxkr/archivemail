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
 
; Override $refentry-body$ from dbrfntry.dsl
; to add a hr after the refentry title h1.
(define ($refentry-body$)
  (let ((id (element-id (current-node))))
    (make sequence
      (make element gi: "H1"
            (make sequence
              (make element gi: "A"
                    attributes: (list (list "NAME" id))
                    (empty-sosofo))
              (element-title-sosofo (current-node))))
      ; Now add hr element after h1. 
      (make empty-element gi: "HR")
      (process-children))))

</style-specification-body>
</style-specification>
<external-specification id="docbook" document="dbstyle">
</style-sheet>
