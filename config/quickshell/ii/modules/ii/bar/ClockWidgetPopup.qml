import qs.modules.common
import qs.modules.common.widgets
import qs.services
import qs.modules.common.functions
import QtQuick
import QtQuick.Layouts

StyledPopup {
    id: root
    contentHoverTracking: true
    animated: true
    popupOpenDelay: 500
    popupCloseDelay: 1800
    popupContentPadding: 4
    // Keep Wayland popupWindow height stationary during calendar expand/collapse animations.
    targetContentHeight: headerBlock.implicitHeight + statusRow.implicitHeight
        + ((root.calendarExpanded || calendarReveal.implicitHeight > 0)
            ? calendarContent.implicitHeight
            : 0)
    popupBackgroundOpacity: {
        const glassEnabled = Config.options.bar.showBackground && Config.options.bar.floatingIsland.glassEnabled;
        const islandOpacity = glassEnabled
            ? Math.max(0, Math.min(100, Config.options.bar.floatingIsland.glassOpacity)) / 100
            : 0;
        return 0.28 + islandOpacity * 0.34;
    }
    popupLayerNamespace: "quickshell:clock-popup"

    property date selectedDate: new Date(
        DateTime.clock.date.getFullYear(), DateTime.clock.date.getMonth(), DateTime.clock.date.getDate()
    )
    property date displayedMonth: new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1)
    property string formattedDate: DateTime.locale.toString(selectedDate, "dddd, d MMMM")
    property string formattedTime: DateTime.time
    property string formattedUptime: DateTime.uptime
    property int pendingTaskCount: Todo.list.filter(item => !item.done).length
    property string todoPreview: getUpcomingTodos()
    property var weekDayNames: makeWeekDayNames()
    property var calendarDays: makeCalendarDays()
    property bool calendarExpanded: false

    function makeWeekDayNames() {
        const firstDay = DateTime.locale.firstDayOfWeek;
        const result = [];
        for (let i = 0; i < 7; i++) {
            const localeDay = ((firstDay - 1 + i) % 7) + 1;
            const date = new Date(2024, 0, localeDay);
            result.push(date.toLocaleDateString(DateTime.locale, "ddd").slice(0, 2));
        }
        return result;
    }

    function makeCalendarDays() {
        const year = displayedMonth.getFullYear();
        const month = displayedMonth.getMonth();
        const monthStart = new Date(year, month, 1);
        const localeFirstDay = DateTime.locale.firstDayOfWeek % 7;
        const offset = (monthStart.getDay() - localeFirstDay + 7) % 7;
        const gridStart = new Date(year, month, 1 - offset);
        const result = [];
        for (let i = 0; i < 42; i++) {
            const dayDate = new Date(gridStart);
            dayDate.setDate(gridStart.getDate() + i);
            result.push({
                date: dayDate,
                day: dayDate.getDate(),
                inMonth: dayDate.getMonth() === month,
                today: DateUtils.sameDate(dayDate, DateTime.clock.date),
                selected: DateUtils.sameDate(dayDate, selectedDate)
            });
        }
        return result;
    }

    function shiftMonth(amount) {
        displayedMonth = new Date(displayedMonth.getFullYear(), displayedMonth.getMonth() + amount, 1);
    }

    function chooseDate(date) {
        selectedDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        if (displayedMonth.getFullYear() !== date.getFullYear() || displayedMonth.getMonth() !== date.getMonth())
            displayedMonth = new Date(date.getFullYear(), date.getMonth(), 1);
    }

    function jumpToToday() {
        const today = DateTime.clock.date;
        selectedDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
        displayedMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    }

    function getUpcomingTodos() {
        const unfinishedTodos = Todo.list.filter(item => !item.done);
        if (unfinishedTodos.length === 0) return "";
        const preview = unfinishedTodos.slice(0, 2).map((item, index) => `${index + 1}. ${item.content}`).join("   ·   ");
        return unfinishedTodos.length > 2
            ? `${preview}   ·   ${Translation.tr("... and %1 more").arg(unfinishedTodos.length - 2)}`
            : preview;
    }

    onDisplayedMonthChanged: calendarDays = makeCalendarDays()
    onSelectedDateChanged: calendarDays = makeCalendarDays()

    ColumnLayout {
        id: columnLayout
        anchors.centerIn: parent
        implicitWidth: 238
        width: implicitWidth
        spacing: 0

        HoverHandler {
            onHoveredChanged: root.contentHovered = hovered
        }

        ColumnLayout {
            id: headerBlock
            Layout.fillWidth: true
            spacing: 0

            StyledText {
                Layout.fillWidth: true
                text: root.formattedTime
                font.family: Appearance.font.family.expressive
                font.pixelSize: 28
                font.weight: Font.DemiBold
                color: Appearance.colors.colOnSurface
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 2

                StyledText {
                    Layout.fillWidth: true
                    text: root.formattedDate
                    font.pixelSize: Appearance.font.pixelSize.small
                    color: Appearance.colors.colOnSurfaceVariant
                }

                RippleButton {
                    implicitWidth: 24
                    implicitHeight: 18
                    buttonRadius: Appearance.rounding.full
                    onClicked: root.calendarExpanded = !root.calendarExpanded
                    contentItem: MaterialSymbol {
                        text: root.calendarExpanded ? "expand_less" : "calendar_month"
                        iconSize: Appearance.font.pixelSize.small
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        color: Appearance.colors.colOnSurfaceVariant
                    }
                }
            }
        }

        RowLayout {
            id: statusRow
            Layout.fillWidth: true
            spacing: 8

            RowLayout {
                spacing: 5
                MaterialSymbol {
                    text: "timelapse"
                    iconSize: Appearance.font.pixelSize.small
                    color: Appearance.m3colors.m3primary
                }
                StyledText {
                    text: root.formattedUptime
                    font.pixelSize: Appearance.font.pixelSize.smaller
                    color: Appearance.colors.colOnSurfaceVariant
                }
            }

            RowLayout {
                spacing: 5
                MaterialSymbol {
                    text: "checklist"
                    iconSize: Appearance.font.pixelSize.small
                    color: Appearance.m3colors.m3primary
                }
                StyledText {
                    text: `${root.pendingTaskCount} · ${Translation.tr("Pending tasks")}`
                    font.pixelSize: Appearance.font.pixelSize.smaller
                    color: Appearance.colors.colOnSurfaceVariant
                }
            }
        }

        Item {
            id: calendarReveal
            Layout.fillWidth: true
            Layout.minimumHeight: 0
            Layout.preferredHeight: implicitHeight
            implicitHeight: root.calendarExpanded ? calendarContent.implicitHeight : 0
            clip: true
            opacity: root.calendarExpanded ? 1 : 0

            Behavior on implicitHeight {
                NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
            }
            Behavior on opacity {
                NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
            }

            ColumnLayout {
                id: calendarContent
                anchors.left: parent.left
                anchors.right: parent.right
                spacing: 6

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 1
                    color: Appearance.colors.colOutlineVariant
                    opacity: 0.5
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        StyledText {
                            Layout.fillWidth: true
                            text: DateTime.locale.toString(root.displayedMonth, "MMMM yyyy")
                            font.pixelSize: Appearance.font.pixelSize.normal
                            font.weight: Font.DemiBold
                            color: Appearance.colors.colOnSurface
                        }

                        RippleButton {
                            implicitWidth: 38
                            implicitHeight: 28
                            buttonRadius: Appearance.rounding.full
                            onClicked: root.jumpToToday()
                            contentItem: StyledText {
                                text: Translation.tr("Today")
                                font.pixelSize: Appearance.font.pixelSize.smaller
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                color: Appearance.colors.colOnLayer1
                            }
                        }

                        RippleButton {
                            implicitWidth: 28
                            implicitHeight: 28
                            buttonRadius: Appearance.rounding.full
                            onClicked: root.shiftMonth(-1)
                            contentItem: MaterialSymbol {
                                text: "chevron_left"
                                iconSize: Appearance.font.pixelSize.normal
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                color: Appearance.colors.colOnLayer1
                            }
                        }

                        RippleButton {
                            implicitWidth: 28
                            implicitHeight: 28
                            buttonRadius: Appearance.rounding.full
                            onClicked: root.shiftMonth(1)
                            contentItem: MaterialSymbol {
                                text: "chevron_right"
                                iconSize: Appearance.font.pixelSize.normal
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                color: Appearance.colors.colOnLayer1
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Repeater {
                            model: root.weekDayNames
                            delegate: StyledText {
                                required property string modelData
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                text: modelData
                                font.pixelSize: Appearance.font.pixelSize.smaller
                                color: Appearance.colors.colOutlineVariant
                            }
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 7
                        rowSpacing: 1
                        columnSpacing: 2

                        Repeater {
                            model: root.calendarDays
                            delegate: Rectangle {
                                id: dayCell
                                required property var modelData
                                Layout.preferredWidth: 29
                                Layout.preferredHeight: 27
                                radius: Appearance.rounding.full
                                color: modelData.selected
                                    ? Appearance.m3colors.m3primary
                                    : modelData.today ? Appearance.colors.colLayer1Hover : "transparent"

                                Behavior on color {
                                    ColorAnimation { duration: 140; easing.type: Easing.OutCubic }
                                }

                                StyledText {
                                    anchors.fill: parent
                                    text: dayCell.modelData.day
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    font.pixelSize: Appearance.font.pixelSize.small
                                    font.weight: (dayCell.modelData.today || dayCell.modelData.selected)
                                        ? Font.DemiBold : Font.Normal
                                    color: dayCell.modelData.selected
                                        ? Appearance.m3colors.m3onPrimary
                                        : dayCell.modelData.inMonth
                                            ? Appearance.colors.colOnLayer1
                                            : Appearance.colors.colOutlineVariant
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.chooseDate(dayCell.modelData.date)
                                }
                            }
                        }
                    }
                }

                StyledText {
                    Layout.fillWidth: true
                    visible: root.pendingTaskCount > 0
                    text: root.todoPreview
                    horizontalAlignment: Text.AlignLeft
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    font.pixelSize: Appearance.font.pixelSize.smaller
                    color: Appearance.colors.colOnSurfaceVariant
                }
            }
        }
    }
}
