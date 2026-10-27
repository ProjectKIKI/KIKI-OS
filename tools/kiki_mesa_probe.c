/* Candidate runtime verification: compile a shader, render, and read it back. */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <gbm.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static GLuint shader(GLenum type, const char *source) {
    GLuint s=glCreateShader(type);GLint ok=0;
    glShaderSource(s,1,&source,NULL);glCompileShader(s);glGetShaderiv(s,GL_COMPILE_STATUS,&ok);
    if(!ok){char log[2048];glGetShaderInfoLog(s,sizeof(log),NULL,log);fprintf(stderr,"shader: %s\n",log);exit(3);}return s;
}
int main(void) {
    PFNEGLGETPLATFORMDISPLAYEXTPROC platform=(PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    if(!platform)return 2;
    EGLDisplay display=platform(EGL_PLATFORM_SURFACELESS_MESA,EGL_DEFAULT_DISPLAY,NULL);
    EGLint major,minor,count;EGLConfig config;
    const EGLint attributes[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT_KHR,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};
    const EGLint context_attributes[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
    const EGLint surface_attributes[]={EGL_WIDTH,4,EGL_HEIGHT,4,EGL_NONE};
    if(!eglInitialize(display,&major,&minor)||!eglBindAPI(EGL_OPENGL_ES_API)||!eglChooseConfig(display,attributes,&config,1,&count)||count!=1)return 4;
    EGLContext context=eglCreateContext(display,config,EGL_NO_CONTEXT,context_attributes);
    EGLSurface surface=eglCreatePbufferSurface(display,config,surface_attributes);
    if(context==EGL_NO_CONTEXT||surface==EGL_NO_SURFACE||!eglMakeCurrent(display,surface,surface,context))return 5;
    GLuint vertex=shader(GL_VERTEX_SHADER,"#version 300 es\nvoid main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}");
    GLuint fragment=shader(GL_FRAGMENT_SHADER,"#version 300 es\nprecision highp float;out vec4 color;void main(){color=vec4(0.25,0.5,0.75,1.0);}");
    GLuint program=glCreateProgram();GLint linked=0;glAttachShader(program,vertex);glAttachShader(program,fragment);glLinkProgram(program);glGetProgramiv(program,GL_LINK_STATUS,&linked);if(!linked)return 6;
    GLuint vao;glGenVertexArrays(1,&vao);glBindVertexArray(vao);glUseProgram(program);glViewport(0,0,4,4);glDrawArrays(GL_TRIANGLES,0,3);glFinish();
    unsigned char pixel[4]={0};glReadPixels(1,1,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel);
    if(glGetError()!=GL_NO_ERROR||abs((int)pixel[0]-64)>2||abs((int)pixel[1]-128)>2||abs((int)pixel[2]-191)>2||pixel[3]!=255)return 7;
    int fd=-1;char drm_device[64]="none";struct gbm_device *gbm=NULL;
    for(int i=0;i<64;i++){char candidate[64];snprintf(candidate,sizeof(candidate),"/dev/dri/card%d",i);fd=open(candidate,O_RDWR|O_CLOEXEC);if(fd>=0){snprintf(drm_device,sizeof(drm_device),"%s",candidate);break;}}
    if(fd>=0){gbm=gbm_create_device(fd);if(!gbm)return 8;}
    printf("{\"passed\":true,\"egl\":\"%d.%d\",\"vendor\":\"%s\",\"renderer\":\"%s\",\"gl_version\":\"%s\",\"pixel\":[%u,%u,%u,%u],\"gbm_backend\":\"%s\",\"drm_device\":\"%s\"}\n",major,minor,glGetString(GL_VENDOR),glGetString(GL_RENDERER),glGetString(GL_VERSION),pixel[0],pixel[1],pixel[2],pixel[3],gbm?gbm_device_get_backend_name(gbm):"no-drm-device",drm_device);
    if(gbm)gbm_device_destroy(gbm);if(fd>=0)close(fd);
    eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);eglDestroyContext(display,context);eglDestroySurface(display,surface);eglTerminate(display);return 0;
}
