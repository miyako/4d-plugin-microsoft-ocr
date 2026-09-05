![platform](https://img.shields.io/static/v1?label=platform&message=win-32%20|%20win-64&color=blue)
![version](https://img.shields.io/badge/version-17%2B-3E8B93)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-microsoft-ocr)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-microsoft-ocr/total)

# 4d-plugin-microsoft-ocr

This plugin runs native optical character recognition on Windows by driving the built-in `Windows.Media.Ocr` API through C++/WinRT — no cloud service, no external dependency, no network call. You pass it raw image bytes (a `Blob`) and it gives back an `Object` containing the recognized text, plus each recognized word's text and pixel-accurate bounding box.

## Summary

| Command | Returns | Purpose |
|---|---|---|
| [`ocr get text`](#ocr-get-text) | Object | Recognize text in an image, with per-word bounding boxes |
| [`ocr get info`](#ocr-get-info) | Object | List the OCR-capable languages installed on this machine |

**Platforms:** Windows only. There is no macOS build of this plugin (the source has no `#if VERSIONMAC` branch at all, and the plugin's own release badge lists `win-32`/`win-64` only) — calling either command on macOS is not a supported configuration.

---

## Requirements & platform notes

- **Windows 10 or later.** `OcrEngine`, the underlying WinRT class this plugin calls, was introduced in Windows 10 build 10.0.10240.0 and hasn't changed its minimum requirement since.
- **At least one OCR language pack installed.** Text recognition depends entirely on OCR language components installed on the machine (Settings → Time & Language → Language & region → language details → "Optical character recognition"). A machine with zero OCR language packs installed will get back an empty result rather than an error — see [`ocr get text`](#ocr-get-text) below.
- **Neither command takes an optional first parameter — `ocr get text`'s *second* parameter is the only optional one.** The image (`Blob`) is always required; the language tag can be omitted.
- **Failure inside OCR is reported via an `error` key on the returned object, not a 4D error/exception.** Both commands always return an `Object` on every call; check for the presence of an `error` property rather than wrapping the call in `ON ERR CALL`.

---

## ocr get text

### Syntax
```
ocr get text ( image ; language ) -> Object
```

| Parameter | Type | Description |
|---|---|---|
| `image` | Blob | Raw bytes of the image to recognize (e.g. from `Document.getContent()`). Any format `Windows.Graphics.Imaging.BitmapDecoder` can decode — JPEG, PNG, BMP, GIF, TIFF are all supported by the underlying Windows codec set. |
| `language` | Text | Optional. A BCP-47 language tag (e.g. `"ja"`, `"en-US"`) telling the engine which language to recognize. Get valid values from the `languageTag` property returned by [`ocr get info`](#ocr-get-info). If omitted, blank, or not a well-formed tag, the plugin falls back to the OCR engine for the user's own profile languages. |
| Result | Object | See return shape below. |

### Return shape

| Property | Type | Description |
|---|---|---|
| `fullText` | Text | The complete recognized text, as one string with the engine's own line breaks. |
| `lines` | Collection | One element per recognized line. Each element is itself a **Collection of word objects** (see below) — there's no separate line-level object; the line's own text isn't returned separately, only assembled per word. |
| `error` | Text | Present only if recognition failed (e.g. the image bytes couldn't be decoded). When present, `fullText`/`lines` are not set. |

Each word object inside a `lines` element has:

| Property | Type | Description |
|---|---|---|
| `word` | Text | The recognized word. |
| `x` | Real | Left edge of the word's bounding box, in pixels from the top-left corner of the image. |
| `y` | Real | Top edge of the word's bounding box, in pixels from the top-left corner of the image. |
| `width` | Real | Width of the bounding box, in pixels. |
| `height` | Real | Height of the bounding box, in pixels. |

### Description

If `image` is an empty blob (zero length), the command returns immediately with an empty `Object` — no `fullText`, `lines`, or `error` key at all, and no 4D error is raised. This is a silent no-op, not a failure signal; check the blob's own size before calling if you need to distinguish "nothing to OCR" from "OCR found nothing."

The `language` parameter only *filters which recognition language is used* — it doesn't change what formats or sizes of image are accepted. If the tag you pass doesn't resolve to any OCR language installed on the machine, or if you omit it, the plugin recognizes using whatever language the user's Windows profile is set to (via `OcrEngine.TryCreateFromUserProfileLanguages`). If the machine has no OCR language installed at all — for either the requested language or the user's profile — the command returns an empty `fullText`/no `lines`, without an `error` key, since this is a normal "nothing to recognize with" outcome rather than an exceptional failure.

The `x`/`y`/`width`/`height` values come directly from the OCR engine's own word-level bounding rectangle, measured in pixels from the image's top-left corner, assuming the recognized text isn't rotated. If a line of text is detected at an angle, the coordinates still describe the box in the original (unrotated) image's coordinate space.

### Example

From the plugin's own test method (`TEST.4dm`):
```4d
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
```

Recognize using the default/profile language (language tag omitted), matching the plugin's own README example:
```4d
$file:=Folder:C1567(fk resources folder:K87:11).file("4d-website-jpr.jpg")
$data:=$file.getContent()
$status:=ocr get text ($data)

If (Is defined($status.error))
	ALERT("OCR failed: "+$status.error)
Else 
	ALERT($status.fullText)
End if 
```

Draw a box around every recognized word (illustrative — combine with 4D's own picture/drawing commands for your target surface):
```4d
$status:=ocr get text ($data;"en")

If (Is defined($status.lines))
	For each ($line; $status.lines)
		For each ($word; $line)
			// $word.word / $word.x / $word.y / $word.width / $word.height
		End for each 
	End for each 
End if 
```

---

## ocr get info

### Syntax
```
ocr get info -> Object
```

| Parameter | Type | Description |
|---|---|---|
| Result | Object | See return shape below. |

### Return shape

| Property | Type | Description |
|---|---|---|
| `languages` | Collection | One element per OCR-capable language installed on this machine. Always present, even on failure (empty in that case). |
| `error` | Text | Present only if the language list couldn't be retrieved. |

Each element of `languages` is an object:

| Property | Type | Description |
|---|---|---|
| `nativeName` | Text | The language's own name, in that language (e.g. `日本語`). |
| `displayName` | Text | The language's name in the current display language. |
| `languageTag` | Text | The BCP-47 tag to pass as `ocr get text`'s second parameter (e.g. `ja`). |
| `script` | Text | The script subtag (e.g. `Jpan`). |

### Description

This lists only languages that actually have an OCR component installed — not every language Windows is displaying in, and not every language the OS could theoretically support. If the returned `languages` collection is empty, no OCR language pack is installed on the machine at all, and `ocr get text` will return empty results regardless of what tag you pass it.

### Example

From the plugin's own test method (`TEST.4dm`):
```4d
$status:=ocr get info 
/*
get supported languages
{nativeName:日本語,displayName:日本語,languageTag:ja,script:Jpan}
use the "tag" for optional $2 to ocr get text
*/
```

Build a menu of available OCR languages:
```4d
$status:=ocr get info 

If (Is defined($status.error))
	ALERT("Could not list OCR languages: "+$status.error)
Else 
	For each ($lang; $status.languages)
		// $lang.displayName / $lang.languageTag
	End for each 
End if 
```

---

## Error handling & troubleshooting

- **Check for an `error` property, not a 4D error trap.** Both commands always return an `Object`; they don't raise a 4D-level exception when OCR itself fails, so `ON ERR CALL` won't catch a decode/recognition failure — inspect the returned object instead.
- **An empty `image` blob returns a silently empty object.** No `fullText`, `lines`, or `error` key is set. If your code assumes one of those keys is always present, guard with `Is defined(...)` first.
- **No OCR language installed produces an empty result, not an error.** If `ocr get info` comes back with an empty `languages` collection, `ocr get text` will never return recognized words no matter what language tag you pass — the fix is installing an OCR language pack in Windows Settings, not adjusting the plugin call.
- **An unresolvable or malformed `language` tag silently falls back to the user's profile language(s)** rather than failing — it will not raise an error and will not necessarily match the language you intended if the tag was simply a typo. Validate tags against [`ocr get info`](#ocr-get-info)'s own `languageTag` values if exact-language matching matters to you.
- **Corrupt or non-image data in `image` surfaces as an `error` key** describing the underlying decode failure (from `Windows.Graphics.Imaging.BitmapDecoder`) rather than a specific 4D error code — treat any non-empty `error` as "could not process this image" and consult the message text for detail.
- **Windows only.** There is no macOS equivalent of this plugin; don't call these commands from code paths meant to run cross-platform.

---

## Quick reference

```4d
// discover languages
$info:=ocr get info 
$tag:=$info.languages[0].languageTag

// recognize an image
$data:=Folder:C1567(fk resources folder:K87:11).file("sample.jpg").getContent()
$result:=ocr get text ($data;$tag)

If (Is defined($result.error))
	ALERT($result.error)
Else 
	ALERT($result.fullText)
	For each ($line; $result.lines)
		For each ($word; $line)
			// $word.word, $word.x, $word.y, $word.width, $word.height
		End for each 
	End for each 
End if 
```
