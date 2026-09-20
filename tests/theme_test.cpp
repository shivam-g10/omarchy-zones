#include "theme.hpp"
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void write(const std::filesystem::path& path, const std::string& contents) {
    std::ofstream file(path);
    file << contents;
    require(bool(file), "Cannot write theme fixture");
}
struct Fixture {
    std::filesystem::path path;
    Fixture() {
        char pattern[] = "/tmp/zones-theme-XXXXXX";
        const auto directory = ::mkdtemp(pattern);
        require(directory, "Cannot create theme fixture");
        path = directory;
    }
    ~Fixture() { std::error_code error; std::filesystem::remove_all(path, error); }
};
}

int main() {
    using namespace zones::theme;
    try {
        require(parseColor("#123456") == 0x123456ff, "RGB alpha default is wrong");
        require(parseColor("rgba(12345678)") == 0x12345678, "RGBA alpha was discarded");
        require(parseColor("#abc8") == 0xaabbcc88, "Short RGBA color was misread");
        require(!parseColor("#12345z") && !parseColor("rgba(123456)"), "Malformed colors accepted");
        const auto gradient = parseGradient("rgba(ff000080) #00ff00 rgb(0000ff) 45deg");
        require(gradient && gradient->colors == std::vector<Color>{0xff000080, 0x00ff00ff, 0x0000ffff}
                && gradient->angle == 45, "Gradient stops or alpha lost");
        const auto live = parseGradient("80ff0000 ff00ff00 ff0000ff 45deg", true);
        require(live == gradient, "Hyprctl ARGB conversion is wrong");
        require(!parseGradient("#ffffff nan deg") && !parseGradient("#ffffff nandeg")
                && !parseGradient("#ffffff 20deg #000000"), "Invalid gradient angle accepted");
        std::string excessive;
        for (int i = 0; i < 33; ++i) excessive += "#ffffff ";
        require(!parseGradient(excessive), "Gradient allocation is unbounded");

        Fixture fixture;
        write(fixture.path / "colors.toml",
              "background = '#001122'\nforeground = '#eeeeee'\naccent = '#aabbcc' # inline comment\n"
              "red = '#cc4455'\nhyprland_active_border = 'rgba(ff000080) #0000ff 45deg'\n");
        write(fixture.path / "shell.toml",
              "[font]\nbase-size = 14\n[controls]\nnormal-fill-alpha = 0.12\n"
              "normal-border = 'rgba(ffffff80) #000000 90deg'\nnormal-border-width = 3\n"
              "focus-fill-alpha = 0.19\nselected-fill-alpha = 0.27\npressed-fill-alpha = 0.3\n");
        auto theme = load(fixture.path);
        require(theme.background == 0x001122ff && theme.error == 0xcc4455ff && theme.accent == 0xaabbccff,
                "Theme palette ignored valid TOML values");
        require(theme.fontSize == 14 && theme.normal.fillAlpha == .12 && theme.normal.borderWidth == 3
                && theme.focus.fillAlpha == .19 && theme.selected.fillAlpha == .27,
                "Shell control and font tokens were not applied");
        require(theme.normal.border.colors.front() == 0xffffff80 && theme.normal.border.angle == 90,
                "Control gradient lost alpha or angle");

        write(fixture.path / "shell.toml", "[controls]\nhover-cursor-color = 'accent'\nhover-cursor-fill-alpha = 0.31\n"
              "focus-color = 'inherit'\nselected-color = 'urgent'\npressed-color = 'transparent'\n");
        theme = load(fixture.path);
        require(theme.hover.color == theme.accent && theme.focus.color == theme.accent
                && theme.focus.fillAlpha == .31 && theme.selected.color == theme.error && theme.pressedColor == 0,
                "Shell color roles or focus inheritance were ignored");

        write(fixture.path / "shell.toml", "[font]\nbase-size = inf\n[controls]\nnormal-fill-alpha = -1\nfocus-border-width = 999\n");
        theme = load(fixture.path);
        require(theme.fontSize == 12 && theme.normal.fillAlpha == 0 && theme.focus.borderWidth == 16,
                "Nonfinite or extreme theme numbers were not bounded");
        write(fixture.path / "colors.toml", "accent = invalid #ff0000\n");
        theme = load(fixture.path);
        require(theme.accent != 0xff0000ff && theme.accent != 0xaabbccff,
                "Malformed TOML or previous theme colors survived reload");
        write(fixture.path / "colors.toml", std::string(detail::maxThemeBytes + 1, '#'));
        require(!detail::readFile(fixture.path / "colors.toml"), "Oversized file accepted");
        std::filesystem::remove(fixture.path / "colors.toml");
        require(::mkfifo((fixture.path / "colors.toml").c_str(), 0600) == 0, "Cannot create FIFO fixture");
        require(!detail::readFile(fixture.path / "colors.toml"), "FIFO theme file accepted");
        require(!detail::readFile(fixture.path), "Directory theme file accepted");
        std::cout << "Theme palette, shell controls, gradient alpha, malformed input, and bounded regular-file checks passed.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
