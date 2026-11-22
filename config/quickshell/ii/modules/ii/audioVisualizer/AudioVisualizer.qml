import QtQuick
import Quickshell
import Quickshell.Wayland
import qs
import qs.services
import qs.modules.common.widgets
Scope {
 Variants {
  model: Quickshell.screens
  PanelWindow {
   id: win
   required property var modelData
   readonly property bool gameMode:PulsarGameMode.active
   readonly property bool circular:PulsarAudioVisualizer.options.style.endsWith("-circle")
   readonly property string position:gameMode?"bottom-center":PulsarAudioVisualizer.options.position
   readonly property int visualizerLength:gameMode?Math.min(PulsarAudioVisualizer.options.length,circular?220:520):PulsarAudioVisualizer.options.length
   readonly property int visualizerSize:gameMode?Math.min(PulsarAudioVisualizer.options.size,40):PulsarAudioVisualizer.options.size
   readonly property bool vertical:position==="left-center"||position==="right-center"
   readonly property bool reverse:position==="right-center"
   screen:modelData
   visible:PulsarAudioVisualizer.enabled&&!GlobalStates.screenLocked
   exclusionMode:ExclusionMode.Ignore
   exclusiveZone:0
   color:"transparent"
   mask:Region{}
   WlrLayershell.namespace:"quickshell:pulsarAudioVisualizer"
   WlrLayershell.layer:WlrLayer.Bottom
   WlrLayershell.keyboardFocus:WlrKeyboardFocus.None
   anchors{left:true;right:true;top:true;bottom:true}
   implicitWidth:screen.width
   implicitHeight:screen.height
   PulsarAudioBars {
    readonly property int dimension:Math.min(win.visualizerLength,Math.min(parent.width,parent.height)-40)
    readonly property int vw:win.circular?dimension:(win.vertical?win.visualizerSize:Math.min(win.visualizerLength,parent.width-40))
    readonly property int vh:win.circular?dimension:(win.vertical?Math.min(win.visualizerLength,parent.height-40):win.visualizerSize)
    width:vw;height:vh
    x:win.position.endsWith("left")?24:win.position.endsWith("right")?parent.width-width-24:(parent.width-width)/2
    y:win.position.startsWith("top")?24:win.position.startsWith("bottom")?parent.height-height-24:(parent.height-height)/2
    levels:PulsarAudioVisualizer.levels
    activeColor:PulsarAudioVisualizer.activeColor
    style:PulsarAudioVisualizer.options.style
    vertical:win.vertical
    reverse:win.reverse
   }
  }
 }
}
