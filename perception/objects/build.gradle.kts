plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.perception.objects"
}

dependencies {
    implementation(project(":core"))
    implementation(project(":input:camera"))
}
