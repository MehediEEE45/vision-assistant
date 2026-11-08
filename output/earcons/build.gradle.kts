plugins {
    id("vision.android.library")
}

android {
    namespace = "bd.visionassistant.output.earcons"
}

dependencies {
    implementation(project(":core"))
    implementation(project(":spine:output-arbiter"))
}
