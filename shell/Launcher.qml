import QtQuick
import Quickshell

// On-demand shell entry point. The native editor owns its window and unsaved
// changes; this launcher releases its shell loader immediately after handoff.
Item {
    id: root
    property var shell: null

    function open(_payloadJson) {
        const script = decodeURIComponent(Qt.resolvedUrl("../scripts/launch-editor.sh").toString().replace(/^file:\/\//, ""));
        Quickshell.execDetached(["bash", script]);
        Qt.callLater(function() {
            if (root.shell) root.shell.hide("omarchy-zones");
        });
    }

    // Hiding or disabling the launcher must not discard native editor changes.
    function close() {}
}
