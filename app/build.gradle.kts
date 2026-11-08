plugins {
    // Versions come from buildSrc, which already has AGP and Kotlin on the
    // build classpath. Repeating them here makes plugin resolution fail.
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "bd.visionassistant"
    compileSdk = 34

    defaultConfig {
        applicationId = "bd.visionassistant"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0-phase1"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Kept in sync with Gatt.PROTOCOL_VERSION. The app refuses to pair with
        // a wearable reporting a different major version rather than silently
        // misreading its sensors.
        buildConfigField("int", "WEARABLE_PROTOCOL_VERSION", "1")
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
        }
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation(project(":core"))
    implementation(project(":protocol"))

    implementation(project(":spine:output-arbiter"))
    implementation(project(":spine:intent-router"))
    implementation(project(":spine:session-state"))
    implementation(project(":spine:safety-policy"))

    implementation(project(":input:ble-link"))
    implementation(project(":input:asr"))
    implementation(project(":input:wakeword"))
    implementation(project(":input:gestures"))
    implementation(project(":input:location"))
    implementation(project(":input:camera"))

    implementation(project(":perception:obstacle-fusion"))
    implementation(project(":perception:fall-detect"))
    implementation(project(":perception:ocr"))

    implementation(project(":output:tts"))
    implementation(project(":output:haptics"))
    implementation(project(":output:earcons"))
    implementation(project(":output:messaging"))

    implementation(project(":feature:navigate"))
    implementation(project(":feature:reader"))
    implementation(project(":feature:library"))
    implementation(project(":feature:describe"))
    implementation(project(":feature:sos"))
    implementation(project(":feature:settings-voice"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.androidx.datastore.preferences)

    testImplementation(libs.junit)
    testImplementation(libs.kotlin.test)
}
