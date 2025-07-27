// Christa's Closet client script

// Register the service worker to enable offline caching and PWA install prompts
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker
      .register('/static/service_worker.js')
      .catch(function (err) {
        console.error('Service worker registration failed:', err);
      });
  });
}

// Schedule a daily notification at a specified time string (HH:MM).
// Uses localStorage['notification_time'] or a DEFAULT_NOTIFICATION_TIME global
// if available.  Safari on iOS requires the app to be installed on the home
// screen and notifications granted.
function scheduleNotificationAt(timeStr) {
  function schedule() {
    const now = new Date();
    const target = new Date();
    const parts = timeStr.split(':');
    const hours = parseInt(parts[0], 10);
    const minutes = parseInt(parts[1], 10);
    target.setHours(hours, minutes, 0, 0);
    if (target <= now) {
      target.setDate(target.getDate() + 1);
    }
    const timeout = target.getTime() - now.getTime();
    setTimeout(() => {
      new Notification('Rise & shine, Christa! Ready to glow today?', {
        body: 'Tap to open Christa\'s Closet for your outfit.',
      });
      schedule();
    }, timeout);
  }
  schedule();
}

function setupNotifications() {
  if (!('Notification' in window)) return;
  Notification.requestPermission().then((permission) => {
    if (permission !== 'granted') return;
    const stored = localStorage.getItem('notification_time');
    const defaultTime = typeof window.DEFAULT_NOTIFICATION_TIME !== 'undefined' ? window.DEFAULT_NOTIFICATION_TIME : '08:00';
    const timeStr = stored || defaultTime || '08:00';
    scheduleNotificationAt(timeStr);
  });
}

// Setup share button functionality if present
function setupShare() {
  const btn = document.getElementById('share-btn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    // Build a share text from the outfit list
    const list = document.querySelector('.outfit-list');
    let text = 'My outfit from Christa\'s Closet:\n';
    if (list) {
      const items = list.querySelectorAll('li');
      items.forEach((li) => {
        text += li.textContent.trim() + '\n';
      });
    }
    if (navigator.share) {
      navigator.share({
        title: 'Today\'s Outfit',
        text: text,
        url: window.location.href,
      }).catch((err) => {
        console.error('Share failed', err);
      });
    } else if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        alert('Outfit details copied to clipboard!');
      });
    } else {
      alert(text);
    }
  });
}

// Listen for DOMContentLoaded to initialise features
document.addEventListener('DOMContentLoaded', () => {
  setupNotifications();
  setupShare();
  // If the settings page is loaded, update localStorage when the time input changes
  const nt = document.getElementById('nt');
  if (nt) {
    nt.addEventListener('change', (e) => {
      localStorage.setItem('notification_time', e.target.value);
    });
  }
});