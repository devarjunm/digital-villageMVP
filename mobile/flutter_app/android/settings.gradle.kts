pluginManagement {
    val flutterSdkPath =
        run {
            val properties = java.util.Properties()
            file("local.properties").inputStream().use { properties.load(it) }
            val flutterSdkPath = properties.getProperty("flutter.sdk")
            require(flutterSdkPath != null) { "flutter.sdk not set in local.properties" }
            flutterSdkPath
        }

    includeBuild("$flutterSdkPath/packages/flutter_tools/gradle")

    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

plugins {
    id("dev.flutter.flutter-plugin-loader") version "1.0.0"
    id("com.android.application") version "9.1.0" apply false
    // Declared (not applied): Flutter validates the Kotlin version of the project,
    // and plugins that ship Kotlin sources need it. The app module itself is Java
    // only (see app/src/main/java/.../MainActivity.java), which keeps the Kotlin
    // compiler out of this module's build.
    id("org.jetbrains.kotlin.android") version "2.4.0" apply false
}

include(":app")
