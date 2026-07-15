// Initializes the Firebase app using the public web config injected by the
// server-rendered page (window.__FIREBASE_CONFIG__). Firebase's web config
// values are not secrets - access control is enforced server-side by
// Ask Oufy's own email allow-list (see app/auth.py), not by hiding this
// config from the browser.
firebase.initializeApp(window.__FIREBASE_CONFIG__);

const askOufyAuth = firebase.auth();
