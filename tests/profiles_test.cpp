#include "profiles.hpp"
#include <cassert>
#include <climits>
#include <iostream>
#include <sstream>

namespace {
using namespace zones;

Profiles read(const std::string& text, bool* legacy = nullptr) {
    std::istringstream input(text);
    Profiles profiles;
    std::string error;
    if (!readProfiles(input, profiles, error, legacy)) {
        std::cerr << error << '\n';
        assert(false);
    }
    assert(error.empty());
    return profiles;
}

void rejected(const std::string& text) {
    const Profiles original{{"Untouched", {{"DP-9", {{0, 0, 100, 100}}}}}};
    Profiles profiles = original;
    std::string error;
    bool legacy = true;
    std::istringstream input(text);
    assert(!readProfiles(input, profiles, error, &legacy));
    assert(!error.empty());
    assert(profiles == original);
    assert(legacy); // Failed reads do not update the format flag either.
}

void invalid(const Profiles& profiles) {
    std::string error;
    assert(!validateProfiles(profiles, error));
    assert(!error.empty());
    std::ostringstream output;
    output << "unchanged";
    assert(!writeProfiles(output, profiles, error));
    assert(output.str() == "unchanged");
}
} // namespace

int main() {
    using namespace zones;
    bool legacy = false;
    auto migrated = read("omarchy-zones-v1\r\n# Existing layout\r\nDP-2 0 0 640 480\r\nDISCONNECTED 640 0 640 480", &legacy);
    assert(legacy);
    assert(migrated.size() == 1 && migrated.front().name == "Default");
    assert((migrated[0].layouts.at("DP-2")[0] == Rect{0, 0, 640, 480}));
    assert(migrated[0].layouts.contains("DISCONNECTED"));
    assert((read("omarchy-zones-v1\n") == Profiles{{"Default", {}}}));

    const Profiles multiple{
        {"Work \"wide\" \\ layout", {{"DP-2", {{0, 0, 640, 480}, {640, 0, 640, 480}}}, {"DISCONNECTED-2", {{0, 0, 400, 400}}}}},
        {"Empty", {}},
        {"अध्ययन", {{"DP-2", {{0, 0, 1280, 480}}}}},
        {"Case", {{"profile", {{0, 0, 32, 32}}}}},
        {"case", {}}
    };
    std::ostringstream serialized;
    std::string error = "stale";
    assert(writeProfiles(serialized, multiple, error));
    assert(error.empty());
    legacy = true;
    assert(read(serialized.str(), &legacy) == multiple);
    assert(!legacy);
    assert(serialized.str().find("profile \"Empty\"\n") != std::string::npos);
    assert(validateProfiles(multiple, error)); // Same rectangle may appear in different profiles.
    assert(validateProfiles({{"A", {{"M1", {{0, 0, 100, 100}}}, {"M2", {{0, 0, 100, 100}}}}}}, error));

    invalid({});
    invalid({{"A", {}}, {"A", {}}});
    invalid({{"A", {{"DP-2", {{0, 0, 640, 480}, {639, 0, 640, 480}}}}}});
    invalid({{"A", {{"DP-2", {{INT_MAX, 0, INT_MAX, 32}}}}}});
    invalid({{"A", {{"DP-2", {{0, 0, 31, 32}}}}}});
    invalid({{"A", {{"DP-2", {{-1, 0, 32, 32}}}}}});
    invalid({{"A", {{"#comment", {{0, 0, 32, 32}}}}}});
    invalid({{"A", {{"has space", {{0, 0, 32, 32}}}}}});
    for (const auto& name : std::vector<std::string>{"", " leading", "trailing ", "\t", "A\tB", "A\x7F", "\xC0\x80", "\xED\xA0\x80", "\xF4\x90\x80\x80", "\xC2\xA0" "leading", "trailing\xE3\x80\x80", std::string(65, 'a')})
        invalid({{name, {}}});
    assert(validateProfiles({{std::string(64, 'a'), {}}}, error));
    invalid({{std::string(22, 'a') + "अध्ययनअध्ययनअध्ययन", {}}}); // The limit counts UTF-8 bytes.
    invalid({{"A", {{std::string(129, 'M'), {{0, 0, 32, 32}}}}}});
    assert(validateProfiles({{"Extent", {{"DP-2", {{32736, 32736, 32, 32}}}}}}, error));

    for (const auto& text : std::vector<std::string>{
        "", "omarchy-zones-v3\n", "omarchy-zones-v2\n", "omarchy-zones-v2\nDP-2 0 0 32 32\n",
        "omarchy-zones-v2\nprofile Unquoted\n", "omarchy-zones-v2\nprofile \"unterminated\n",
        "omarchy-zones-v2\nprofile \"Name\" junk\n", "omarchy-zones-v2\nprofile \"Name\"\nDP-2 0 0 32 32 junk\n",
        "omarchy-zones-v2\nprofile \"Name\"\nDP-2 0 0 32 32 # inline comment\n",
        "omarchy-zones-v2\nprofile \"Name\"\nDP-2 0 0 32.0 32\n",
        "omarchy-zones-v2\nprofile \"Name\"\nDP-2 nan 0 32 32\n",
        "omarchy-zones-v2\nprofile \"Name\"\nDP-2 +-0 0 32 32\n",
        "omarchy-zones-v2\nprofile \"Name\"\nDP-2 0 0 999999999999999999999 32\n",
        "omarchy-zones-v2\nprofile \"Name\"\nDP-2 32768 0 32 32\n",
        "omarchy-zones-v1\nDP-2 0 0 32 32\nDP-2 1 0 32 32\n",
        "omarchy-zones-v2\nprofile \"Same\"\nprofile \"Same\"\n"})
        rejected(text);
    assert((read("omarchy-zones-v1\nDP-2 +0 -0 +32 32\n")[0].layouts.at("DP-2")[0] == Rect{0, 0, 32, 32}));

    Profiles maximum;
    for (std::size_t p = 0; p < maxProfiles; ++p) {
        Profile profile{"Profile " + std::to_string(p), {}};
        for (std::size_t z = 0; z < maxZonesPerProfile; ++z)
            profile.layouts["DP-2"].push_back({static_cast<int>(32 * z), 0, 32, 32});
        maximum.push_back(profile);
    }
    assert(validateProfiles(maximum, error));
    std::ostringstream full;
    assert(writeProfiles(full, maximum, error));
    assert(read(full.str()) == maximum);
    auto tooMany = maximum;
    tooMany.push_back({"Thirteenth", {}});
    invalid(tooMany);
    rejected(full.str() + "profile \"Thirteenth\"\n");
    tooMany = maximum;
    tooMany[0].layouts["DISCONNECTED"].push_back({0, 0, 32, 32});
    invalid(tooMany);
    rejected(full.str() + "DISCONNECTED 0 0 32 32\n");

    rejected("omarchy-zones-v2\nprofile \"A\"\n#" + std::string(maxProfileLineBytes, 'x') + "\n");
    std::string oversized = "omarchy-zones-v2\nprofile \"A\"\n";
    while (oversized.size() <= maxProfileFileBytes) oversized += "# comment\n";
    rejected(oversized);
    std::istringstream badInput("omarchy-zones-v2\nprofile \"A\"\n");
    badInput.setstate(std::ios::badbit);
    Profiles untouched = multiple;
    assert(!readProfiles(badInput, untouched, error));
    assert(untouched == multiple);
    std::ostringstream badOutput;
    badOutput.setstate(std::ios::badbit);
    assert(!writeProfiles(badOutput, multiple, error));

    std::cout << "Profile migration, round trips, isolation, strict parsing, limits, and atomic failure passed.\n";
}
