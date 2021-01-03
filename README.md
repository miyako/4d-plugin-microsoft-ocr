![platform](https://img.shields.io/static/v1?label=platform&message=win-32%20|%20win-64&color=blue)
![version](https://img.shields.io/badge/version-17%2B-3E8B93)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-microsoft-ocr)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-microsoft-ocr/total)

# 4d-plugin-microsoft-ocr
Use native OCR (C++/WinRT) on Windows.

Thanks to [C++/WinRT](https://blogs.windows.com/windowsdeveloper/2016/11/28/standard-c-windows-runtime-cwinrt/), it is no longer necessary to use all sorts of [tricks and marchaling](https://qiita.com/Yukio-Ichikawa/items/f8d3111a60a337adfd48) to call [Universal Windows Platform](https://en.wikipedia.org/wiki/Universal_Windows_Platform) API from C++. This plugin is using the [Windows.Media.Ocr](https://docs.microsoft.com/en-us/uwp/api/Windows.Media.Ocr?view=winrt-19041) API. 

#### Visual Studio 2017

To enable `co_await`

* add the compiler flag `/await` to project
* set the c++ language standard to `ISO C++ Latest Draft Standard (/std:c++latest)`
* add `windowsapp.lib` to additional libraries

![image](https://github.com/miyako/4d-plugin-microsoft-ocr/blob/main/OCR/test/Resources/4d-website-jpr.jpg)

The project requires `10.0.17763` SDK, released in conjunction with Windows 10 version 1809.

#### Example

```4d
$file:=Folder:C1567(fk resources folder:K87:11).file("4d-website-jpr.jpg")
$data:=$file.getContent()
$status:=ocr get text ($data)
```

![screenshot](https://user-images.githubusercontent.com/1725068/103483342-f40c3b00-4e29-11eb-95ab-bfd62f265208.png)

