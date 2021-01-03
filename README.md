![platform](https://img.shields.io/static/v1?label=platform&message=win-32%20|%20win-64&color=blue)
![version](https://img.shields.io/badge/version-17%2B-3E8B93)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-microsoft-ocr)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-microsoft-ocr/total)

# 4d-plugin-microsoft-ocr
Use native OCR (C++/WinRT) on Windows.

Thanks to [C++/WinRT](https://blogs.windows.com/windowsdeveloper/2016/11/28/standard-c-windows-runtime-cwinrt/), it is no longer necessary to use all sorts of [tricks and marchaling](https://qiita.com/Yukio-Ichikawa/items/f8d3111a60a337adfd48) to call [Universal Windows Platform](https://en.wikipedia.org/wiki/Universal_Windows_Platform) API from native C++. This plugin is using the [Windows.Media.Ocr](https://docs.microsoft.com/en-us/uwp/api/Windows.Media.Ocr?view=winrt-19041) API. 

#### Visual Studio 2017

To enable `co_await`

* add the compiler flag `/await` to project
* set the c++ language standard to `ISO C++ Latest Draft Standard (/std:c++latest)`
* add `windowsapp.lib` to additional libraries

#### Example

<img width="900" alt="screenshot" src="https://user-images.githubusercontent.com/1725068/103483067-100edd00-4e28-11eb-82ac-b52cb5030368.png">
