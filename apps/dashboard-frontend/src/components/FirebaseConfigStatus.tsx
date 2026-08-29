"use client";

export function FirebaseConfigStatus() {
  const config = {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
    messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  };

  const missing = [];
  if (!config.apiKey) missing.push('API_KEY');
  if (!config.authDomain) missing.push('AUTH_DOMAIN');
  if (!config.projectId) missing.push('PROJECT_ID');
  if (!config.appId) missing.push('APP_ID');

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
      <div className="max-w-md w-full bg-white rounded-lg shadow-lg p-6">
        <div className="text-center mb-6">
          <div className="mx-auto h-12 w-12 bg-red-100 rounded-full flex items-center justify-center mb-4">
            <svg className="h-6 w-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
          </div>
          <h3 className="text-lg font-medium text-gray-900">Firebase Configuration Required</h3>
        </div>

        {missing.length > 0 ? (
          <div className="space-y-4">
            <div className="bg-red-50 border border-red-200 rounded-md p-4">
              <h4 className="text-sm font-medium text-red-800 mb-2">Missing Configuration:</h4>
              <ul className="text-sm text-red-700 space-y-1">
                {missing.map(key => (
                  <li key={key}>• NEXT_PUBLIC_FIREBASE_{key}</li>
                ))}
              </ul>
            </div>

            <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
              <h4 className="text-sm font-medium text-blue-800 mb-2">Setup Steps:</h4>
              <ol className="text-sm text-blue-700 space-y-1 list-decimal list-inside">
                <li>Go to <a href="https://console.firebase.google.com" className="underline" target="_blank">Firebase Console</a></li>
                <li>Open "hawanama-2" project</li>
                <li>Go to Project Settings → General → Your apps</li>
                <li>Copy the Firebase config values</li>
                <li>Add them to .env.local</li>
                <li>Run: npm run build && npx firebase deploy --only hosting</li>
              </ol>
            </div>
          </div>
        ) : (
          <div className="bg-green-50 border border-green-200 rounded-md p-4">
            <p className="text-sm text-green-700">✅ Firebase configuration is complete!</p>
            <pre className="text-xs text-green-600 mt-2 bg-green-100 p-2 rounded overflow-hidden">
              Project: {config.projectId}{'\n'}
              Domain: {config.authDomain}{'\n'}
              API Key: {config.apiKey?.slice(0, 6)}...
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}