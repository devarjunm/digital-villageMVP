// AGP 9 deprecates the legacy `android {}` extension accessor; the Flutter Gradle
// plugin still configures that path (the template sets android.newDsl=false), so
// the deprecation is silenced here instead of rewriting the module against the
// new DSL ahead of the Flutter template.
@file:Suppress("DEPRECATION")

import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android plugin.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.digitalvillage.digital_village_app"
    compileSdk = flutter.compileSdkVersion
    // No NDK: nothing in this app (or in its plugins) ships native code compiled
    // at build time, so declaring one would only make the build download ~1 GB.

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.digitalvillage.digital_village_app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        // 23 is required by flutter_secure_storage's EncryptedSharedPreferences,
        // which backs the access/refresh token store.
        minSdk = maxOf(23, flutter.minSdkVersion)
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    // A production release must be signed with a real upload key. Create
    // android/key.properties (git-ignored) with storeFile/storePassword/keyAlias/
    // keyPassword and Gradle will use it; without it, release builds fall back to
    // the debug key so `flutter run --release` still works locally. A
    // debug-signed release APK must never be uploaded to Play.
    val keystoreProperties = Properties()
    val keystoreFile = rootProject.file("key.properties")
    if (keystoreFile.exists()) {
        keystoreFile.inputStream().use { keystoreProperties.load(it) }
    }
    signingConfigs {
        if (keystoreFile.exists()) {
            create("release") {
                storeFile = file(keystoreProperties["storeFile"] as String)
                storePassword = keystoreProperties["storePassword"] as String
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (keystoreFile.exists()) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }
}

flutter {
    source = "../.."
}
