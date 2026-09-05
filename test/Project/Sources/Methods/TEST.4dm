//%attributes = {}
$status:=ocr get info 
/*
get supported languages
{nativeName:日本語,displayName:日本語,languageTag:ja,script:Jpan}
use the "tag" for optional $2 to ocr get text
*/

$file:=Folder:C1567(fk resources folder:K87:11).file("4d-website-jpr.jpg")

$data:=$file.getContent()

$status:=ocr get text ($data;"ja")