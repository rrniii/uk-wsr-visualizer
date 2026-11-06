#include <jni.h>
#include <string>
#include <vector>
#include <cstdio>
#include "UKHDF5Reader.h"

static void fail(JNIEnv *env,const char *message) {
    jclass type=env->FindClass("java/io/IOException");
    if(type && !env->ExceptionCheck()) env->ThrowNew(type,message);
}
class Utf {
    JNIEnv* env; jstring value; const char* ptr;
public:
    Utf(JNIEnv* e,jstring s):env(e),value(s),ptr(s?e->GetStringUTFChars(s,nullptr):nullptr){}
    ~Utf(){if(ptr)env->ReleaseStringUTFChars(value,ptr);}
    const char* get(){return ptr?ptr:"";}
};
extern "C" JNIEXPORT jobject JNICALL Java_com_rrniii_ukwsrvisualizer_NativeBridge_readNative(JNIEnv* env,jobject,jstring path,jstring dataset,jstring quantity) {
    Utf p(env,path),d(env,dataset),q(env,quantity);
    if(env->ExceptionCheck()) return nullptr;
    UKHDF5PolarField f{}; char error[1024]{};
    if(!UKHDF5ReadODIMField(p.get(),d.get(),q.get(),&f,error,sizeof(error))){fail(env,error);return nullptr;}
    struct Cleanup { UKHDF5PolarField* field; ~Cleanup(){UKHDF5FreePolarField(field);} } cleanup{&f};
    jclass type=env->FindClass("com/rrniii/ukwsrvisualizer/NativeField");
    if(!type) return nullptr;
    jmethodID ctor=env->GetMethodID(type,"<init>","()V");
    if(!ctor)return nullptr;
    jobject out=env->NewObject(type,ctor);
    if(!out)return nullptr;
    auto objectField=[&](const char* name,const char* sig,jobject v){if(!v||env->ExceptionCheck())return; auto id=env->GetFieldID(type,name,sig);if(id)env->SetObjectField(out,id,v);env->DeleteLocalRef(v);};
    auto number=[&](const char* name,double v){if(env->ExceptionCheck())return;auto id=env->GetFieldID(type,name,"D");if(id)env->SetDoubleField(out,id,v);};
    auto integer=[&](const char* name,int v){if(env->ExceptionCheck())return;auto id=env->GetFieldID(type,name,"I");if(id)env->SetIntField(out,id,v);};
    jfloatArray values=env->NewFloatArray(f.valueCount); if(!values)return nullptr;env->SetFloatArrayRegion(values,0,f.valueCount,f.values);objectField("values","[F",values);
    jbyteArray states=env->NewByteArray(f.valueCount);if(!states)return nullptr;env->SetByteArrayRegion(states,0,f.valueCount,reinterpret_cast<jbyte*>(f.sourceStates));objectField("sourceStates","[B",states);
    jdoubleArray start=env->NewDoubleArray(f.rows);
    if(!start)return nullptr;
    jdoubleArray stop=env->NewDoubleArray(f.rows);
    if(!stop)return nullptr;
    env->SetDoubleArrayRegion(start,0,f.rows,f.startAzimuthDeg);env->SetDoubleArrayRegion(stop,0,f.rows,f.stopAzimuthDeg);
    objectField("startAzimuths","[D",start);objectField("stopAzimuths","[D",stop);
    integer("rows",f.rows);integer("columns",f.columns);
    integer("measuredAzimuths",f.measuredAzimuths);
    number("latitude",f.latitude);number("longitude",f.longitude);number("heightM",f.heightM);number("elevationDeg",f.elevationDeg);number("rstartKm",f.rstartKm);number("rscaleM",f.rscaleM);number("beamWidthDeg",f.beamWidthDeg);
    objectField("dataset","Ljava/lang/String;",env->NewStringUTF(f.datasetName));objectField("quantity","Ljava/lang/String;",env->NewStringUTF(f.quantity));
    return env->ExceptionCheck()?nullptr:out;
}
extern "C" JNIEXPORT jobjectArray JNICALL Java_com_rrniii_ukwsrvisualizer_NativeBridge_inspectNative(JNIEnv* env,jobject,jstring path) {
    Utf p(env,path);if(env->ExceptionCheck())return nullptr;std::vector<UKHDF5FieldRecord> records(4096);int count=0;char error[1024]{};
    if(!UKHDF5InspectODIMFields(p.get(),records.data(),records.size(),&count,error,sizeof(error))){fail(env,error);return nullptr;}
    jclass string=env->FindClass("java/lang/String");if(!string)return nullptr;jobjectArray out=env->NewObjectArray(count,string,nullptr);if(!out)return nullptr;
    for(int i=0;i<count;i++){auto &r=records[i];char line[512];snprintf(line,sizeof(line),"%s\t%s\t%d\t%d\t%.12g",r.datasetName,r.quantity,r.rows,r.columns,r.elevationDeg);jstring s=env->NewStringUTF(line);if(!s)return nullptr;env->SetObjectArrayElement(out,i,s);env->DeleteLocalRef(s);}
    return out;
}
