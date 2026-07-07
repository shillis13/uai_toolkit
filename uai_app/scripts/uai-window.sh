#!/bin/bash
# UAI Window Management Helper
# Usage: uai-window.sh [raise|screenshot|click X Y|info]

CMD="${1:-info}"
TITLE="UAI"

case "$CMD" in
  raise)
    osascript -e "
    tell application \"System Events\"
      set allProcs to every process
      repeat with p in allProcs
        try
          set wins to every window of p
          repeat with w in wins
            if name of w contains \"$TITLE\" then
              set frontmost of p to true
              perform action \"AXRaise\" of w
              return \"Raised: \" & name of w
            end if
          end repeat
        end try
      end repeat
      return \"Window not found\"
    end tell
    "
    ;;
  screenshot)
    osascript -e "
    tell application \"System Events\"
      set allProcs to every process
      repeat with p in allProcs
        try
          set wins to every window of p
          repeat with w in wins
            if name of w contains \"$TITLE\" then
              set frontmost of p to true
              perform action \"AXRaise\" of w
            end if
          end repeat
        end try
      end repeat
    end tell
    "
    sleep 0.5
    screencapture -x /tmp/uai_screenshot.png
    echo "Saved to /tmp/uai_screenshot.png"
    ;;
  click)
    X="${2:?X coordinate required}"
    Y="${3:?Y coordinate required}"
    cliclick c:"$X","$Y"
    ;;
  info)
    osascript -e "
    tell application \"System Events\"
      set res to \"\"
      set allProcs to every process
      repeat with p in allProcs
        try
          set wins to every window of p
          repeat with w in wins
            if name of w contains \"$TITLE\" then
              set pos to position of w
              set sz to size of w
              set res to \"Window: \" & name of w & \" pos=\" & (item 1 of pos) & \",\" & (item 2 of pos) & \" size=\" & (item 1 of sz) & \"x\" & (item 2 of sz)
              return res
            end if
          end repeat
        end try
      end repeat
      return \"Window not found\"
    end tell
    "
    ;;
  *)
    echo "Usage: uai-window.sh [raise|screenshot|click X Y|info]"
    ;;
esac
