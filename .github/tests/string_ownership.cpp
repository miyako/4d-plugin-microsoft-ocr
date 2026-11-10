#include "4DPlugin-JSON.h"
#include "PrivateTypes.h"
#include "EntryPoints.h"

#include <cassert>
#include <cstdlib>
#include <set>

static std::set<PA_Unichar *> owned;
static CUTF16String property;
static bool allocateEmpty = true;

static PA_Unistring createString(const PA_Unichar *text)
{
    PA_Unistring result = {};
    while (text[result.fLength])
        ++result.fLength;
    if (result.fLength || allocateEmpty)
    {
        result.fString = new PA_Unichar[result.fLength + 1];
        std::copy(text, text + result.fLength + 1, result.fString);
        assert(owned.insert(result.fString).second);
    }
    return result;
}

static void disposeString(PA_Unistring *text)
{
    if (text->fString)
    {
        assert(owned.erase(text->fString) == 1);
        delete[] text->fString;
    }
    *text = {};
}

static void host(short selector, EngineBlock *eb)
{
    switch (selector)
    {
        case EX_CREATE_UNISTRING:
            eb->fUniString1 = createString(
                reinterpret_cast<const PA_Unichar *>(eb->fHandle));
            break;
        case EX_DISPOSE_UNISTRING:
            disposeString(&eb->fUniString1);
            break;
        case EX_CLEAR_VARIABLE:
        {
            auto *variable = static_cast<PA_Variable *>(eb->fPtr1);
            assert(variable->fType == eVK_Unistring);
            disposeString(&variable->uValue.fString);
            variable->fType = eVK_Undefined;
            break;
        }
        case EX_SET_OBJ_VALUE:
        {
            auto *variable = static_cast<PA_Variable *>(eb->fPtr2);
            assert(variable->fType == eVK_Unistring);
            const auto &text = variable->uValue.fString;
            if (text.fString)
            {
                assert(owned.count(text.fString) == 1);
                property.assign(text.fString, text.fLength);
            }
            else
                property.clear();
            break;
        }
        default:
            std::abort();
    }
    eb->fError = eER_NoErr;
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    gCall4D = host;
    allocateEmpty = std::atoi(argv[2]) != 0;
    int objectToken = 0;
    PA_ObjectRef object = &objectToken;
    const PA_Unichar unicode[] = {0x65e5, 0x672c, 0xd83d, 0xde00, 0};
    CUTF16String expected(unicode);
    ob_set_s(nullptr, "key", "value");
    ob_set_s(object, "key", nullptr);
    ob_set_s(nullptr, L"key", "value");
    ob_set_s(object, L"key", nullptr);
    ob_set_a(nullptr, L"key", L"value");
    ob_set_a(object, L"key", static_cast<const wchar_t *>(nullptr));
    ob_set_a(nullptr, L"key", &expected);
    ob_set_a(object, L"key", static_cast<const CUTF16String *>(nullptr));
    assert(owned.empty());
    for (int i = 0; i != 20; ++i)
    {
        bool empty = i % 2;
        property.assign(1, '!');
        switch (std::atoi(argv[1]))
        {
            case 0:
                ob_set_s(object, "key", empty ? "" : "\xe6\x97\xa5\xe6\x9c\xac\xf0\x9f\x98\x80");
                break;
            case 1:
                ob_set_s(object, L"key", empty ? "" : "\xe6\x97\xa5\xe6\x9c\xac\xf0\x9f\x98\x80");
                break;
            case 2:
                ob_set_a(object, L"key", empty ? L"" : L"\u65e5\u672c\U0001f600");
                break;
            case 3:
            {
                CUTF16String value = empty ? CUTF16String() : expected;
                ob_set_a(object, L"key", &value);
                break;
            }
            default:
                std::abort();
        }
        assert(property == (empty ? CUTF16String() : expected));
        // The property copy survives local cleanup; no temporary owner leaks.
        assert(owned.empty());
    }
}
