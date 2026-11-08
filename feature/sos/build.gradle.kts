plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.feature.sos"
}

dependencies {
    implementation(project(":core"))
    implementation(project(":spine:output-arbiter"))
    implementation(project(":spine:session-state"))
    implementation(project(":perception:fall-detect"))
    implementation(project(":input:location"))
}
