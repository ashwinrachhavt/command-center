// Keep application progress open while the user moves between form steps.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

// The saved application stays in the workspace; discard only closed-tab UI state.
chrome.tabs.onRemoved.addListener((tabId) => {
  void chrome.storage.local.remove(`applicationDraft:${tabId}`);
});
