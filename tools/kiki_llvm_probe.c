/* Exercise the rebuilt target LLVM C API, verifier and native JIT. */
#include <llvm-c/Core.h>
#include <llvm-c/Analysis.h>
#include <llvm-c/ExecutionEngine.h>
#include <llvm-c/Target.h>
#include <stdint.h>
#include <stdio.h>

int main(void) {
    LLVMLinkInMCJIT();
    if (LLVMInitializeNativeTarget() || LLVMInitializeNativeAsmPrinter()) return 2;
    LLVMContextRef context = LLVMContextCreate();
    LLVMModuleRef module = LLVMModuleCreateWithNameInContext("kiki-native-check", context);
    LLVMBuilderRef builder = LLVMCreateBuilderInContext(context);
    LLVMTypeRef integer = LLVMInt32TypeInContext(context);
    LLVMValueRef function = LLVMAddFunction(module, "kiki_answer", LLVMFunctionType(integer, NULL, 0, 0));
    LLVMBasicBlockRef entry = LLVMAppendBasicBlockInContext(context, function, "entry");
    LLVMPositionBuilderAtEnd(builder, entry);
    LLVMBuildRet(builder, LLVMConstInt(integer, 42, 0));
    char *error = NULL;
    if (LLVMVerifyModule(module, LLVMReturnStatusAction, &error)) {
        fprintf(stderr, "LLVM verifier: %s\n", error); LLVMDisposeMessage(error); return 3;
    }
    LLVMDisposeMessage(error);
    LLVMExecutionEngineRef engine;
    if (LLVMCreateExecutionEngineForModule(&engine, module, &error)) {
        fprintf(stderr, "LLVM JIT: %s\n", error); LLVMDisposeMessage(error); return 4;
    }
    uintptr_t address = (uintptr_t)LLVMGetFunctionAddress(engine, "kiki_answer");
    if (!address) return 5;
    int result = ((int (*)(void))address)();
    LLVMDisposeBuilder(builder); LLVMDisposeExecutionEngine(engine); LLVMContextDispose(context);
    printf("{\"passed\":%s,\"jit_result\":%d,\"expected\":42}\n", result == 42 ? "true" : "false", result);
    return result == 42 ? 0 : 6;
}
